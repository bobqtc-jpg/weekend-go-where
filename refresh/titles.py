"""List the events already saved, so extraction can reuse their titles.

Usage:
    python -m refresh.titles

Prints one line per event that has not ended: dates, title and venue. When an article
describes one of these events, the candidate should copy its title and venue name exactly,
so refresh.merge folds the article in as another source.
"""
from __future__ import annotations

import sys

from .common import EVENTS_FILE, load_json, sg_today


def main() -> int:
    today = sg_today().isoformat()
    events = [e for e in load_json(EVENTS_FILE, {"events": []})["events"] if e["dates"]["end"] >= today]
    for e in sorted(events, key=lambda e: (e["dates"]["start"], e["title"].lower())):
        print(f"{e['dates']['start']} to {e['dates']['end']} | {e['title']} | {e['venue']['name']}")
    print(f"{len(events)} saved event(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
