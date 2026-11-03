"""Print the coming weekend's events as Markdown, grouped by how long they last.

Usage:
    python -m refresh.preview                    # the coming Saturday and Sunday
    python -m refresh.preview --date 2026-11-14  # the weekend on or after a date
    python -m refresh.preview --all-ages         # include events marked unsuitable for a toddler

Groups:
    Limited time  one-offs and runs of up to `limited_max_days`, plus longer runs that end
                  within `last_chance_days` of the Saturday ("last chance"); soonest ending first
    Every week    repeats on a schedule with no near end (dates.pattern "recurring")
    Ongoing       longer runs, and anything with no stated end (dates.pattern "open_ended")
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from .common import CONFIG_DIR, EVENTS_FILE, load_json, load_yaml, sg_today

DAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
TODDLER_RANK = {"yes": 0, "unclear": 1, "no": 2}
GROUPS = [("limited", "Limited time"), ("weekly", "Every week"), ("ongoing", "Ongoing")]
DEFAULT_LIMITED_MAX_DAYS = 42
DEFAULT_LAST_CHANCE_DAYS = 14


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


def classify(
    event: dict,
    saturday: date,
    limited_max_days: int = DEFAULT_LIMITED_MAX_DAYS,
    last_chance_days: int = DEFAULT_LAST_CHANCE_DAYS,
) -> str:
    """'limited', 'last_chance', 'weekly' or 'ongoing' for the weekend starting on `saturday`."""
    pattern = event["dates"].get("pattern") or "fixed"
    if pattern == "recurring":
        return "weekly"
    if pattern == "open_ended":
        return "ongoing"
    start = date.fromisoformat(event["dates"]["start"])
    end = date.fromisoformat(event["dates"]["end"])
    if (end - start).days + 1 <= limited_max_days:
        return "limited"
    if end < saturday + timedelta(days=last_chance_days):
        return "last_chance"
    return "ongoing"


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


def group_events(events: list[dict], saturday: date, limited_max_days: int, last_chance_days: int) -> dict[str, list]:
    """Events by group; limited time (with last chance) sorted by end date, others keep their order."""
    groups: dict[str, list] = {key: [] for key, _ in GROUPS}
    for e in events:
        kind = classify(e, saturday, limited_max_days, last_chance_days)
        groups["limited" if kind == "last_chance" else kind].append((kind, e))
    groups["limited"].sort(key=lambda item: item[1]["dates"]["end"])  # stable: toddler order within a day
    return groups


def _short(d: str, year: int) -> str:
    """'7 Nov', or '19 Sep 2027' when the year differs from the weekend's."""
    day = date.fromisoformat(d)
    return day.strftime("%-d %b" if day.year == year else "%-d %b %Y")


def _cell(text: str | None) -> str:
    return (text or "").replace("|", "/").replace("\n", " ").strip()


def _row(kind: str, e: dict, saturday: date, sunday: date) -> str:
    on = "/".join(label for d, label in ((saturday, "Sat"), (sunday, "Sun")) if runs_on(e, d))
    start, end = e["dates"]["start"], e["dates"]["end"]
    if kind == "weekly":
        span = ""
    elif kind == "last_chance":
        span = f", last chance: ends {_short(end, saturday.year)}"
    elif e["dates"].get("pattern") == "open_ended":
        span = f", from {_short(start, saturday.year)}, end not stated"
    else:
        span = "" if start == end else f", {_short(start, saturday.year)} to {_short(end, saturday.year)}"
    when = f"{on}{span}" + (f"; {e['dates']['times']}" if e["dates"].get("times") else "")
    cost = e["cost"]
    price = "Free" if cost.get("is_free") is True else (cost.get("price_text") or "Not stated")
    status = (e.get("booking") or {}).get("status")
    if status in ("fully_booked", "registration_required"):
        price += "; " + status.replace("_", " ")
    sources = ", ".join(sorted({s["source_id"] for s in e["sources"]}))
    return (
        f"| {_cell(e['title'])} | {_cell(when)} | {_cell(e['venue']['name'])} | {_cell(price)} "
        f"| {e['audience']['toddler_ok']} | {e['setting']} | {sources} |"
    )


def render(events: list[dict], saturday: date, sunday: date, limited_max_days: int, last_chance_days: int) -> str:
    groups = group_events(events, saturday, limited_max_days, last_chance_days)
    lines = [f"Weekend of {saturday.strftime('%a %-d %b')} and {sunday.strftime('%a %-d %b %Y')}: {len(events)} event(s)"]
    for key, heading in GROUPS:
        lines += ["", f"## {heading} ({len(groups[key])})", ""]
        if not groups[key]:
            lines.append("None.")
            continue
        lines += [
            "| Event | When | Where | Price | Toddler | Setting | Sources |",
            "|---|---|---|---|---|---|---|",
        ]
        lines += [_row(kind, e, saturday, sunday) for kind, e in groups[key]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show the coming weekend's events.")
    parser.add_argument("--date", type=date.fromisoformat, help="use the weekend on or after this date")
    parser.add_argument("--all-ages", action="store_true", help="include events marked unsuitable for a toddler")
    args = parser.parse_args(argv)
    planning = load_yaml(CONFIG_DIR / "settings.yaml").get("planning", {})
    saturday, sunday = next_weekend(args.date or sg_today())
    store = load_json(EVENTS_FILE, {"events": []})
    events = weekend_events(store["events"], saturday, sunday, args.all_ages)
    print(
        render(
            events,
            saturday,
            sunday,
            int(planning.get("limited_max_days", DEFAULT_LIMITED_MAX_DAYS)),
            int(planning.get("last_chance_days", DEFAULT_LAST_CHANCE_DAYS)),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
