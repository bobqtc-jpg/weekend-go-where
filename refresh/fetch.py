"""Fetch the newest articles from each configured source into inbox/.

Usage:
    python -m refresh.fetch                 # every source in config/sources.yaml
    python -m refresh.fetch bykido timeout  # selected sources only
    python -m refresh.fetch --force         # refetch even if unchanged

Each article lands in inbox/articles/<key>.json with its URL, title, publish date
and main text as Markdown, with links kept so booking URLs survive.
inbox/manifest.json lists what was fetched for this run. An article whose text is
unchanged since it was last merged (per data/seen.json) is skipped, so a page that
is rewritten every week is re-read only when it actually changes.
"""
from __future__ import annotations

import argparse
import html as htmllib
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Callable, Iterator
from urllib import robotparser
from urllib.parse import urlencode, urlparse

import feedparser
import lxml.html
import requests
import trafilatura

from .common import (
    ARTICLES_DIR,
    CONFIG_DIR,
    MANIFEST_FILE,
    ROOT,
    SEEN_FILE,
    content_hash,
    load_json,
    load_yaml,
    sg_now,
    sg_today,
    slugify,
    write_json,
)

USER_AGENT = "weekend-go-where/0.1 (personal family planner; one run a week)"
REQUEST_DELAY_S = 2.0
TIMEOUT_S = 30
MIN_TEXT_CHARS = 200


@dataclass
class Article:
    source_id: str
    url: str
    title: str
    published: str | None
    text: str

    @property
    def key(self) -> str:
        path = urlparse(self.url).path.strip("/")
        return f"{self.source_id}__{slugify(path or self.title)}"


@dataclass
class Context:
    since: date
    max_items: int
    title_filter: re.Pattern[str]


def robots_from_response(status: int | None, text: str) -> robotparser.RobotFileParser:
    """Robots rules per RFC 9309: a 4xx means no rules; a 5xx means stay out."""
    rp = robotparser.RobotFileParser()
    if status is not None and 200 <= status < 300:
        rp.parse(text.splitlines())
    elif status is not None and 400 <= status < 500:
        rp.allow_all = True
    else:
        rp.disallow_all = True
    return rp


class Fetcher:
    """Polite HTTP client: one request every couple of seconds, robots.txt respected."""

    def __init__(self, delay_s: float = REQUEST_DELAY_S) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-SG,en;q=0.9"})
        self.delay_s = delay_s
        self._robots: dict[str, robotparser.RobotFileParser] = {}
        self._unreachable: dict[str, str] = {}
        self._last = 0.0

    def _throttle(self, delay_s: float | None = None) -> None:
        wait = (self.delay_s if delay_s is None else delay_s) - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _check_robots(self, url: str) -> robotparser.RobotFileParser:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots and origin not in self._unreachable:
            self._throttle()
            try:
                resp = self.session.get(origin + "/robots.txt", timeout=TIMEOUT_S)
            except requests.RequestException as exc:
                self._unreachable[origin] = f"{type(exc).__name__}: {exc}"
            else:
                self._robots[origin] = robots_from_response(resp.status_code, resp.text)
        if origin in self._unreachable:
            raise ConnectionError(f"cannot reach {origin} ({self._unreachable[origin]})")
        rp = self._robots[origin]
        if not rp.can_fetch(USER_AGENT, url):
            raise PermissionError(f"robots.txt disallows {url}")
        return rp

    def get(self, url: str) -> requests.Response:
        rp = self._check_robots(url)
        # Honour the site's Crawl-delay when it asks for more than our default.
        self._throttle(max(self.delay_s, float(rp.crawl_delay(USER_AGENT) or 0)))
        resp = self.session.get(url, timeout=TIMEOUT_S)
        resp.raise_for_status()
        return resp


def html_to_article(
    html: str,
    url: str,
    source_id: str,
    title: str | None = None,
    published: str | None = None,
) -> Article | None:
    """Pull the main text out of a page as Markdown, keeping links."""
    text = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=True,
        include_tables=True,
        include_comments=False,
        favor_recall=True,
    )
    if not text or len(text) < MIN_TEXT_CHARS:
        return None
    meta = trafilatura.extract_metadata(html, default_url=url)
    if not title and meta is not None and meta.title:
        title = meta.title
    if not published and meta is not None and meta.date:
        published = meta.date[:10]
    return Article(source_id, url, (title or url).strip(), published, text.strip())


def index_links(html: str, base_url: str, pattern: str, exclude: str | None = None) -> list[str]:
    """Links on an index page that match `pattern` (and not `exclude`), absolute, de-duplicated, in page order."""
    doc = lxml.html.document_fromstring(html)
    doc.make_links_absolute(base_url)
    rx = re.compile(pattern)
    rx_exclude = re.compile(exclude) if exclude else None
    links: list[str] = []
    for element, attribute, link, _pos in doc.iterlinks():
        if element.tag != "a" or attribute != "href":
            continue
        link = link.split("#", 1)[0]
        if rx_exclude and rx_exclude.search(link):
            continue
        if link != base_url and rx.search(link) and link not in links:
            links.append(link)
    return links


def _strip_tags(fragment: str) -> str:
    if not fragment.strip():
        return ""
    return " ".join(lxml.html.fromstring(f"<div>{fragment}</div>").text_content().split())


def _entry_date(entry: Any) -> date | None:
    for field in ("published_parsed", "updated_parsed"):
        value = entry.get(field)
        if value:
            return date(value.tm_year, value.tm_mon, value.tm_mday)
    return None


def from_pages(fetcher: Fetcher, source_id: str, strategy: dict, ctx: Context) -> Iterator[Article]:
    for url in strategy["urls"]:
        article = html_to_article(fetcher.get(url).text, url, source_id)
        if article:
            yield article


def from_feed(fetcher: Fetcher, source_id: str, strategy: dict, ctx: Context) -> Iterator[Article]:
    feed = feedparser.parse(fetcher.get(strategy["url"]).content)
    taken = 0
    for entry in feed.entries:
        if taken >= strategy.get("max_items", ctx.max_items):
            break
        published = _entry_date(entry)
        if published and published < ctx.since:
            continue
        title = htmllib.unescape(entry.get("title", "")).strip()
        link = entry.get("link")
        if not link or not ctx.title_filter.search(title):
            continue
        # Feeds often truncate the body, so read the full page.
        article = html_to_article(
            fetcher.get(link).text, link, source_id, title, published.isoformat() if published else None
        )
        if article:
            taken += 1
            yield article


def from_wordpress(fetcher: Fetcher, source_id: str, strategy: dict, ctx: Context) -> Iterator[Article]:
    base = strategy["base"].rstrip("/")
    max_items = strategy.get("max_items", ctx.max_items)
    seen_links: set[str] = set()
    for term in strategy.get("search", [""]):
        params = {
            "search": term,
            "after": f"{ctx.since.isoformat()}T00:00:00",
            "per_page": max_items,
            "orderby": "date",
            "order": "desc",
            "_fields": "date,link,title,content",
        }
        posts = fetcher.get(f"{base}/wp-json/wp/v2/posts?{urlencode(params)}").json()
        for post in posts:
            link = post.get("link")
            if not link or link in seen_links:
                continue
            seen_links.add(link)
            title = _strip_tags(post.get("title", {}).get("rendered", ""))
            if not ctx.title_filter.search(title):
                continue
            body = post.get("content", {}).get("rendered", "")
            page = (
                f"<html><head><title>{htmllib.escape(title)}</title></head>"
                f"<body><article><h1>{htmllib.escape(title)}</h1>{body}</article></body></html>"
            )
            article = html_to_article(page, link, source_id, title, (post.get("date") or "")[:10] or None)
            if article:
                yield article


def from_index(fetcher: Fetcher, source_id: str, strategy: dict, ctx: Context) -> Iterator[Article]:
    index_url = strategy["url"]
    max_items = strategy.get("max_items", ctx.max_items)
    links = index_links(
        fetcher.get(index_url).text, index_url, strategy["link_pattern"], strategy.get("exclude_link_pattern")
    )
    taken = 0
    for link in links[: max_items * 3]:  # cap requests when the title filter rejects many
        if taken >= max_items:
            break
        article = html_to_article(fetcher.get(link).text, link, source_id)
        if article and ctx.title_filter.search(article.title):
            taken += 1
            yield article


STRATEGIES: dict[str, Callable[[Fetcher, str, dict, Context], Iterator[Article]]] = {
    "page": from_pages,
    "feed": from_feed,
    "wordpress": from_wordpress,
    "index": from_index,
}


def run(source_ids: list[str] | None = None, force: bool = False) -> int:
    config = load_yaml(CONFIG_DIR / "sources.yaml")
    defaults = config.get("defaults", {})
    sources = [s for s in config["sources"] if not source_ids or s["id"] in source_ids]
    unknown = set(source_ids or []) - {s["id"] for s in sources}
    if unknown:
        print(f"Unknown source id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    seen = {} if force else load_json(SEEN_FILE, {})
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    for stale in ARTICLES_DIR.glob("*.json"):
        stale.unlink()

    fetcher = Fetcher()
    manifest: dict[str, dict] = {}
    failed = 0
    for source in sources:
        ctx = Context(
            since=sg_today() - timedelta(days=source.get("lookback_days", defaults.get("lookback_days", 10))),
            max_items=source.get("max_items", defaults.get("max_items", 6)),
            title_filter=re.compile(source.get("title_filter", defaults.get("title_filter", "."))),
        )
        new = unchanged = 0
        errors: list[str] = []
        for strategy in source["strategies"]:
            try:
                for article in STRATEGIES[strategy["type"]](fetcher, source["id"], strategy, ctx):
                    digest = content_hash(article.text)
                    if article.key in manifest:
                        continue  # same article reached through two strategies
                    if seen.get(article.url, {}).get("hash") == digest:
                        unchanged += 1
                        continue
                    record = {
                        **asdict(article),
                        "key": article.key,
                        "hash": digest,
                        "fetched_at": sg_now().isoformat(timespec="seconds"),
                    }
                    write_json(ARTICLES_DIR / f"{article.key}.json", record)
                    manifest[article.key] = {
                        k: record[k] for k in ("source_id", "url", "title", "published", "hash")
                    }
                    new += 1
            except Exception as exc:  # one broken source must not stop the others
                errors.append(f"{strategy['type']}: {type(exc).__name__}: {exc}")
        status = "ok" if not errors else ("partial" if new or unchanged else "failed")
        failed += status == "failed"
        print(f"{source['id']:<14} {status:<8} new_or_changed={new} unchanged={unchanged}")
        for error in errors:
            print(f"    ! {error}")

    write_json(MANIFEST_FILE, manifest)
    print(f"\n{len(manifest)} article(s) to extract; list in {MANIFEST_FILE.relative_to(ROOT)}")
    if sources and failed == len(sources):
        print("Every source failed; check network access before going further.", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch new articles into inbox/.")
    parser.add_argument("sources", nargs="*", help="source ids to fetch (default: all)")
    parser.add_argument("--force", action="store_true", help="refetch even if unchanged since the last merge")
    args = parser.parse_args(argv)
    return run(args.sources or None, args.force)


if __name__ == "__main__":
    sys.exit(main())
