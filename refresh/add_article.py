"""Add text that did not come from fetch.py (such as an email digest) to this run's inbox.

Usage:
    python -m refresh.add_article --source muse --title "Singapore toddler happenings - week of 2026-11-10" \
        --url "https://mail.google.com/mail/#all/<thread id>" --published 2026-11-11 --text-file body.txt

Run it after `refresh.fetch`, which starts a fresh manifest. The article then goes
through extraction and merging like any fetched page. Text unchanged since it was
last merged (same URL and content) is skipped unless --force is given.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .common import (
    ARTICLES_DIR,
    MANIFEST_FILE,
    SEEN_FILE,
    content_hash,
    load_json,
    sg_now,
    slugify,
    write_json,
)


def add_article(source: str, title: str, url: str, published: str | None, text: str, force: bool = False) -> str | None:
    """Register one article; returns its key, or None when it is unchanged since the last merge."""
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"url must be http(s): {url}")
    if published is not None:
        date.fromisoformat(published)  # raises on a malformed date
    text = text.strip()
    if not text:
        raise ValueError("text is empty")
    digest = content_hash(text)
    if not force and load_json(SEEN_FILE, {}).get(url, {}).get("hash") == digest:
        return None
    key = f"{slugify(source)}__{slugify(title)}"
    record = {
        "source_id": source,
        "url": url,
        "title": title,
        "published": published,
        "text": text,
        "key": key,
        "hash": digest,
        "fetched_at": sg_now().isoformat(timespec="seconds"),
    }
    write_json(ARTICLES_DIR / f"{key}.json", record)
    manifest = load_json(MANIFEST_FILE, {})
    manifest[key] = {k: record[k] for k in ("source_id", "url", "title", "published", "hash")}
    write_json(MANIFEST_FILE, manifest)
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add an email or other text to this run's inbox.")
    parser.add_argument("--source", required=True, help="source id, e.g. muse")
    parser.add_argument("--title", required=True)
    parser.add_argument("--url", required=True, help="a link back to the original (http or https)")
    parser.add_argument("--published", help="YYYY-MM-DD")
    parser.add_argument("--text-file", required=True, type=Path, help="plain-text body")
    parser.add_argument("--force", action="store_true", help="add even if unchanged since the last merge")
    args = parser.parse_args(argv)
    try:
        key = add_article(
            args.source, args.title, args.url, args.published, args.text_file.read_text(encoding="utf-8"), args.force
        )
    except ValueError as exc:
        print(f"Not added: {exc}", file=sys.stderr)
        return 1
    print(f"Added inbox/articles/{key}.json" if key else "Unchanged since the last merge; skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
