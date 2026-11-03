"""Print the coming weekend's events as a Markdown table, toddler-friendly first.

Usage:
    python -m refresh.preview                    # the coming Saturday and Sunday
    python -m refresh.preview --date 2026-11-14  # the weekend on or after a date
    python -m refresh.preview --all-ages         # include events marked unsuitable for a toddler
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from .common import EVENTS_FILE, load_json, sg_today

DAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
TODDLER_RANK = {"yes": 0, "unclear": 1, "no": 2}


def next_weekend(today: date) -> tuple[date, date]:
    """The Saturday and Sunday of the current week; on a Sunday, the weekend in progress."""
    if today.weekday() == 6:
        return today - timedelta(days=1), today
    saturday = today + timedelta(days=5 - today.weekday())
    return saturday, saturday + timedelta(days=1)


def runs_on(event: dict, day: date) -> bool:
    if not event["dates"]["start"] <= day.isoformat() <= event["dates"]["end"]:
        return False
    days = event["dates"].get("days") or []
    return not days or DAY_CODES[day.weekday()] in days


def weekend_events(events: list[dict], saturday: date, sunday: date, all_ages: bool = False) -> list[dict]:
    picked = [
        e
        for e in events
        if (runs_on(e, saturday) or runs_on(e, sunday))
        and (all_ages or e["audience"]["toddler_ok"] != "no")
    ]
    picked.sort(
        key=lambda e: (
            TODDLER_RANK[e["audience"]["toddler_ok"]],
            e["cost"].get("is_free") is not True,
            e["title"].lower(),
        )
    )
    return picked


def _short(d: str, year: int) -> str:
    """'7 Nov', or '19 Sep 2027' when the year differs from the weekend's."""
    day = date.fromisoformat(d)
    return day.strftime("%-d %b" if day.year == year else "%-d %b %Y")


def _cell(text: str | None) -> str:
    return (text or "").replace("|", "/").replace("\n", " ").strip()


def render(events: list[dict], saturday: date, sunday: date) -> str:
    lines = [
        f"Weekend of {saturday.strftime('%a %-d %b')} and {sunday.strftime('%a %-d %b %Y')}: {len(events)} event(s)",
        "",
        "| Event | When | Where | Price | Toddler | Setting | Sources |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in events:
        on = "/".join(label for d, label in ((saturday, "Sat"), (sunday, "Sun")) if runs_on(e, d))
        start, end = e["dates"]["start"], e["dates"]["end"]
        span = "" if start == end else f", {_short(start, saturday.year)} to {_short(end, saturday.year)}"
        when = f"{on}{span}" + (f"; {e['dates']['times']}" if e["dates"].get("times") else "")
        cost = e["cost"]
        price = "Free" if cost.get("is_free") is True else (cost.get("price_text") or "Not stated")
        sources = ", ".join(sorted({s["source_id"] for s in e["sources"]}))
        lines.append(
            f"| {_cell(e['title'])} | {_cell(when)} | {_cell(e['venue']['name'])} | {_cell(price)} "
            f"| {e['audience']['toddler_ok']} | {e['setting']} | {sources} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show the coming weekend's events.")
    parser.add_argument("--date", type=date.fromisoformat, help="use the weekend on or after this date")
    parser.add_argument("--all-ages", action="store_true", help="include events marked unsuitable for a toddler")
    args = parser.parse_args(argv)
    saturday, sunday = next_weekend(args.date or sg_today())
    store = load_json(EVENTS_FILE, {"events": []})
    print(render(weekend_events(store["events"], saturday, sunday, args.all_ages), saturday, sunday))
    return 0


if __name__ == "__main__":
    sys.exit(main())
