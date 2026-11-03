"""Check data/events.json and data/places.json against the schemas plus sanity rules.

Usage:
    python -m refresh.validate
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator, FormatChecker

from .common import EVENTS_FILE, PLACES_FILE, SCHEMA_DIR, load_json, sg_today

MAX_RANGE_DAYS = 400
URL_PREFIXES = ("https://", "http://")


def load_validator(schema_name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def schema_errors(item: object, validator: Draft202012Validator) -> list[str]:
    errors = sorted(validator.iter_errors(item), key=lambda e: [str(p) for p in e.absolute_path])
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}" for e in errors]


def event_errors(event: dict, validator: Draft202012Validator, today: date) -> list[str]:
    errors = schema_errors(event, validator)
    if errors:
        return errors
    start = date.fromisoformat(event["dates"]["start"])
    end = date.fromisoformat(event["dates"]["end"])
    if end < start:
        errors.append("dates: end is before start")
    if (end - start).days > MAX_RANGE_DAYS:
        errors.append(f"dates: runs longer than {MAX_RANGE_DAYS} days, so treat it as a place, not an event")
    if start > today + timedelta(days=MAX_RANGE_DAYS):
        errors.append(f"dates: starts more than {MAX_RANGE_DAYS} days from now")
    audience = event["audience"]
    if (
        audience.get("age_min") is not None
        and audience.get("age_max") is not None
        and audience["age_min"] > audience["age_max"]
    ):
        errors.append("audience: age_min is above age_max")
    booking = event.get("booking") or {}
    if booking.get("opens") and booking["opens"] > event["dates"]["end"]:
        errors.append("booking: opens after the event ends")
    urls = [s["url"] for s in event["sources"]] + ([booking["url"]] if booking.get("url") else [])
    errors.extend(f"url: not http(s): {u}" for u in urls if not u.startswith(URL_PREFIXES))
    return errors


def place_errors(place: dict, validator: Draft202012Validator) -> list[str]:
    errors = schema_errors(place, validator)
    if not errors:
        errors.extend(
            f"url: not http(s): {s['url']}" for s in place["sources"] if not s["url"].startswith(URL_PREFIXES)
        )
    return errors


def check_store(path: Path, list_key: str, check: Callable[[dict], list[str]]) -> list[str]:
    store = load_json(path, None)
    if not isinstance(store, dict) or set(store) != {"updated", list_key}:
        return [f"{path.name}: expected an object with keys 'updated' and '{list_key}'"]
    errors: list[str] = []
    if store["updated"] is not None:
        try:
            date.fromisoformat(store["updated"])
        except (TypeError, ValueError):
            errors.append(f"{path.name}: 'updated' is not an ISO date")
    seen_ids: set[str] = set()
    for i, item in enumerate(store[list_key]):
        label = f"{path.name}[{i}]"
        item_id = item.get("id") if isinstance(item, dict) else None
        if item_id in seen_ids:
            errors.append(f"{label}: duplicate id {item_id}")
        if item_id:
            seen_ids.add(item_id)
        errors.extend(f"{label} {problem}" for problem in check(item))
    return errors


def main() -> int:
    today = sg_today()
    event_validator = load_validator("event.schema.json")
    place_validator = load_validator("place.schema.json")
    errors = check_store(EVENTS_FILE, "events", lambda e: event_errors(e, event_validator, today))
    errors += check_store(PLACES_FILE, "places", lambda p: place_errors(p, place_validator))
    if errors:
        print("\n".join(errors))
        print(f"{len(errors)} problem(s) found", file=sys.stderr)
        return 1
    print("data/ is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
