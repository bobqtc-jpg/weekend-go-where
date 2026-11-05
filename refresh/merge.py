"""Merge events extracted from inbox articles into data/events.json.

Usage:
    python -m refresh.merge                 # merge, expire old events, record merged articles
    python -m refresh.merge --dry-run       # report only, write nothing
    python -m refresh.merge --skip-invalid  # merge valid candidates, list the rest

Every article in inbox/manifest.json needs inbox/extracted/<key>.json: a JSON list
of candidate events written by the refresh session (an empty list when the article
has none). This step adds ids, source links and first/last-seen dates, validates
each candidate, folds the same event from different sources into one record, and
drops events that ended more than `keep_ended_events_days` ago.
"""
from __future__ import annotations

import argparse
import copy
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher

from jsonschema import Draft202012Validator

from .common import (
    CONFIG_DIR,
    EVENTS_FILE,
    EXTRACTED_DIR,
    MANIFEST_FILE,
    ROOT,
    SEEN_FILE,
    load_json,
    load_yaml,
    normalize,
    sg_today,
    stable_id,
    write_json,
)
from .validate import event_errors, load_validator

SYSTEM_FIELDS = ("id", "sources", "first_seen", "last_seen")
UNKNOWN = (None, "unclear", "", [])
# When sources disagree: a repeat schedule is the most informative, a placeholder end the least.
PATTERN_PRECEDENCE = ["recurring", "fixed", "open_ended"]
NOTES_MAX = 400  # schema/event.schema.json: notes maxLength


def _pattern(event: dict) -> str:
    return event["dates"].get("pattern") or "fixed"


@dataclass
class MergeReport:
    new: int = 0
    updated: int = 0
    expired: int = 0
    skipped_past: int = 0
    errors: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def similarity(a: str | None, b: str | None) -> float:
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


STOPWORDS = {"the", "a", "an", "at", "of", "and", "in", "on", "for", "with", "by", "to", "singapore", "2026", "2027"}


def _words(text: str | None) -> set[str]:
    """Distinct words, ignoring anything in brackets and very common words."""
    return {w for w in normalize(re.sub(r"\([^)]*\)", " ", text or "")).split() if w not in STOPWORDS}


def _contained(a: set[str], b: set[str]) -> tuple[int, float]:
    """How many words the smaller set shares with the larger, and what share of it that is."""
    if not a or not b:
        return 0, 0.0
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    shared = len(small & big)
    return shared, shared / len(small)


def _days_apart(d1: str, d2: str) -> int:
    return abs((date.fromisoformat(d1) - date.fromisoformat(d2)).days)


def same_event(a: dict, b: dict) -> bool:
    """Same id, or overlapping dates with a near-identical title (or similar title at the same venue).

    Sources also name one event differently ("A Universal Christmas" and "A Universal Christmas at
    Universal Studios Singapore"), so two events also match when they are at the same place, run
    over nearly the same dates, and the shorter title's words mostly appear in the longer one.
    """
    if a["id"] == b["id"]:
        return True
    da, db = a["dates"], b["dates"]
    if not (da["start"] <= db["end"] and db["start"] <= da["end"]):
        return False
    title = similarity(a["title"], b["title"])
    venue = similarity(a["venue"]["name"], b["venue"]["name"])
    if title >= 0.85 or (title >= 0.6 and venue >= 0.8):
        return True
    shared, share = _contained(_words(a["title"]), _words(b["title"]))
    _, venue_share = _contained(_words(a["venue"]["name"]), _words(b["venue"]["name"]))
    same_run = _days_apart(da["start"], db["start"]) <= 7 and _days_apart(da["end"], db["end"]) <= 7
    return shared >= 2 and share >= 0.5 and venue_share >= 0.6 and same_run


def build_event(candidate: dict, article: dict, today: date) -> dict:
    """Turn a candidate into an event. A digest that links each item (such as an email) may give
    the item's own page as `source_url`, which then replaces the article URL as its source link."""
    event = {k: copy.deepcopy(v) for k, v in candidate.items() if k not in SYSTEM_FIELDS + ("source_url",)}
    event["id"] = stable_id(
        "ev",
        candidate.get("title"),
        (candidate.get("venue") or {}).get("name"),
        (candidate.get("dates") or {}).get("start"),
    )
    event["sources"] = [
        {
            "source_id": article["source_id"],
            "url": candidate.get("source_url") or article["url"],
            "article_title": article.get("title"),
            "published": article.get("published"),
        }
    ]
    event["first_seen"] = event["last_seen"] = today.isoformat()
    return event


def _fill_gaps(dst: dict, src: dict) -> None:
    for key, value in src.items():
        if key in SYSTEM_FIELDS:
            continue
        current = dst.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            _fill_gaps(current, value)
        elif current in UNKNOWN and value not in UNKNOWN:
            dst[key] = copy.deepcopy(value)


def append_note(event: dict, note: str, limit: int = NOTES_MAX) -> None:
    """Add a sentence to the event's notes once, keeping the notes within the schema's limit.
    When space runs out, the older text is shortened so the newest note still fits."""
    notes = (event.get("notes") or "").strip()
    if note in notes:
        return
    combined = f"{notes} {note}".strip()
    if len(combined) > limit:
        keep = max(0, limit - len(note) - 2)
        combined = (f"{notes[:keep].rstrip()}… {note}" if keep else note)[:limit]
    event["notes"] = combined


def fold_in(existing: dict, new: dict, today: date) -> None:
    """Merge `new` into `existing`: add its sources, fill unknown fields, widen the dates.

    Sources often differ only because one says "now till X" (start inferred) or gives no end
    (end is a placeholder), so the merged event takes the widest range. Only a clash between
    two stated end dates is worth a note.
    """
    known_urls = {s["url"] for s in existing["sources"]}
    existing["sources"].extend(s for s in new["sources"] if s["url"] not in known_urls)
    existing["last_seen"] = today.isoformat()
    old_pattern, new_pattern = _pattern(existing), _pattern(new)
    has_pattern = "pattern" in existing["dates"] or "pattern" in new["dates"]
    _fill_gaps(existing, new)
    if has_pattern:
        existing["dates"]["pattern"] = min(old_pattern, new_pattern, key=PATTERN_PRECEDENCE.index)
    old_start, old_end = existing["dates"]["start"], existing["dates"]["end"]
    new_start, new_end = new["dates"]["start"], new["dates"]["end"]
    existing["dates"]["start"] = min(old_start, new_start)
    if old_end != new_end:
        if old_pattern == "open_ended" and new_pattern != "open_ended":
            existing["dates"]["end"] = new_end  # a stated end beats a placeholder
        elif new_pattern == "open_ended" and old_pattern != "open_ended":
            existing["dates"]["end"] = old_end
        else:
            existing["dates"]["end"] = max(old_end, new_end)
        if old_pattern == new_pattern == "fixed":
            append_note(existing, f"Sources differ on the end date: {old_end} vs {new_end}.")


def merge(
    existing: list[dict],
    manifest: dict[str, dict],
    extracted: dict[str, object],
    today: date,
    keep_days: int,
    validator: Draft202012Validator,
) -> tuple[list[dict], MergeReport]:
    report = MergeReport()
    events = copy.deepcopy(existing)
    for key, article in manifest.items():
        candidates = extracted.get(key)
        if candidates is None:
            report.missing.append(key)
            continue
        if not isinstance(candidates, list):
            report.errors.append(f"{key}: expected a JSON list, got {type(candidates).__name__}")
            continue
        for i, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                report.errors.append(f"{key}[{i}]: expected an object")
                continue
            event = build_event(candidate, article, today)
            problems = event_errors(event, validator, today)
            if problems:
                report.errors.extend(f"{key}[{i}] {p}" for p in problems)
                continue
            if event["dates"]["end"] < today.isoformat():
                report.skipped_past += 1
                continue
            match = next((e for e in events if same_event(e, event)), None)
            if match is None:
                events.append(event)
                report.new += 1
            else:
                fold_in(match, event, today)
                report.updated += 1
    cutoff = (today - timedelta(days=keep_days)).isoformat()
    kept = [e for e in events if e["dates"]["end"] >= cutoff]
    report.expired = len(events) - len(kept)
    kept.sort(key=lambda e: (e["dates"]["start"], normalize(e["title"])))
    return kept, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge extracted events into data/events.json.")
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    parser.add_argument(
        "--skip-invalid",
        action="store_true",
        help="merge the valid candidates and list the rest instead of stopping (invalid ones are lost)",
    )
    args = parser.parse_args(argv)

    manifest = load_json(MANIFEST_FILE, None)
    if manifest is None:
        print("No inbox/manifest.json; run `python -m refresh.fetch` first.", file=sys.stderr)
        return 1
    settings = load_yaml(CONFIG_DIR / "settings.yaml")
    keep_days = int(settings.get("refresh", {}).get("keep_ended_events_days", 7))
    extracted = {key: load_json(EXTRACTED_DIR / f"{key}.json", None) for key in manifest}
    store = load_json(EVENTS_FILE, {"updated": None, "events": []})
    today = sg_today()

    validator = load_validator("event.schema.json")
    events, report = merge(store["events"], manifest, extracted, today, keep_days, validator)
    # Never write data that refresh.validate would reject.
    report.errors.extend(
        f"merged event '{e['title']}': {p}" for e in events for p in event_errors(e, validator, today)
    )
    print(
        f"new={report.new} updated={report.updated} expired={report.expired} "
        f"skipped_past={report.skipped_past} total={len(events)}"
    )
    for key in report.missing:
        print(f"  missing extraction: inbox/extracted/{key}.json")
    for error in report.errors:
        print(f"  invalid: {error}")
    if report.missing or (report.errors and not args.skip_invalid):
        print("Nothing written. Fix the items above and rerun.", file=sys.stderr)
        return 1
    if args.dry_run:
        print("Dry run: nothing written.")
        return 0

    write_json(EVENTS_FILE, {"updated": today.isoformat(), "events": events})
    seen = load_json(SEEN_FILE, {})
    for article in manifest.values():
        seen[article["url"]] = {"hash": article["hash"], "merged": today.isoformat()}
    write_json(SEEN_FILE, seen)
    print(f"Wrote {len(events)} event(s) to {EVENTS_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
