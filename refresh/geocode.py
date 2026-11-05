"""Find map positions for event venues through OneMap's public search.

Usage:
    python -m refresh.geocode           # look up venues without a position, then fill events.json
    python -m refresh.geocode --retry   # also retry venues that found no match before

Results are cached in data/geocode.json, keyed by venue name and address, so a venue
is looked up once. A match is accepted only when it shares a distinctive word with what
was searched; venues that name several places ("selected fire stations", "16 libraries")
are left without a position. Each new match is printed so a wrong one can be spotted:
to fix one, edit its entry in data/geocode.json (or set lat and lng to null) and rerun.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from typing import Iterable

import requests

from .common import DATA_DIR, EVENTS_FILE, load_json, normalize, write_json

GEOCODE_FILE = DATA_DIR / "geocode.json"
SEARCH_URL = "https://www.onemap.gov.sg/api/common/elastic/search"
DELAY_S = 1.0  # OneMap limits searches made without an account
RETRY_WAITS_S = (15, 45, 90)  # waits after a "too many requests" answer
MULTI_VENUE = re.compile(
    r"\b(selected|participating|various|multiple|islandwide|several|community clubs?|libraries|malls)\b", re.I
)
# Words too common to prove that a search result is the place we asked for.
GENERIC = {
    "singapore", "centre", "center", "level", "hall", "road", "street", "the", "and", "park",
    "mall", "city", "lobby", "atrium", "room", "ground", "floor", "plaza", "square", "theatre",
    "studio", "building", "tower", "east", "west", "north", "south", "central", "main",
}


def cache_key(name: str, address: str | None) -> str:
    return f"{normalize(name)}|{normalize(address)}"


def distinctive_words(text: str) -> set[str]:
    return {w for w in normalize(text).split() if len(w) >= 4 and w not in GENERIC}


POSTAL = re.compile(r"\bS?(\d{6})\b")


def queries_for(name: str, address: str | None) -> list[str]:
    """Search strings to try, most specific first. A postal code alone is the most exact."""
    out: list[str] = []
    if address:
        postal = POSTAL.search(address)
        if postal:
            out.append(postal.group(1))
        out.append(address)
    plain = re.sub(r"\([^)]*\)", " ", name)
    plain = " ".join(plain.split())
    out.append(plain)
    parts = [p.strip() for p in re.split(r",|·", plain) if p.strip()]
    out.extend(reversed(parts))  # the last part is usually the building
    for sep in (" and ", " & ", " or "):
        if sep in plain:
            out.append(plain.split(sep, 1)[0])
    words = parts[0].split() if parts else []
    if len(words) > 3:
        out.extend([" ".join(words[:3]), " ".join(words[:2])])
    seen: set[str] = set()
    return [q for q in out if not (q.lower() in seen or seen.add(q.lower()))]


def accept(query: str, result: dict) -> bool:
    if query.isdigit():
        return result.get("POSTAL") == query
    wanted = distinctive_words(query)
    if not wanted:
        return False
    found = distinctive_words(" ".join(result.get(k) or "" for k in ("SEARCHVAL", "BUILDING", "ADDRESS")))
    return bool(wanted & found)


def search(session: requests.Session, query: str) -> list[dict]:
    params = {"searchVal": query, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1}
    for wait in (*RETRY_WAITS_S, None):
        resp = session.get(SEARCH_URL, params=params, timeout=20)
        if resp.status_code != 429 or wait is None:
            break
        time.sleep(wait)
    resp.raise_for_status()
    return resp.json().get("results") or []


def lookup(session: requests.Session, name: str, address: str | None) -> dict:
    if MULTI_VENUE.search(name) and not address:
        return {"lat": None, "lng": None, "reason": "names several places"}
    for query in queries_for(name, address):
        time.sleep(DELAY_S)
        for result in search(session, query)[:3]:
            if accept(query, result):
                return {
                    "lat": round(float(result["LATITUDE"]), 6),
                    "lng": round(float(result["LONGITUDE"]), 6),
                    "match": result.get("SEARCHVAL"),
                    "query": query,
                }
    return {"lat": None, "lng": None, "reason": "no matching place found"}


def venues(events: Iterable[dict]) -> dict[str, tuple[str, str | None]]:
    return {cache_key(e["venue"]["name"], e["venue"].get("address")): (e["venue"]["name"], e["venue"].get("address")) for e in events}


def run(retry: bool = False) -> int:
    store = load_json(EVENTS_FILE, {"updated": None, "events": []})
    cache: dict = load_json(GEOCODE_FILE, {})
    session = requests.Session()
    session.headers["User-Agent"] = "weekend-go-where/0.1 (personal family planner)"
    looked_up = failed = 0
    for key, (name, address) in sorted(venues(store["events"]).items()):
        if key in cache and not (retry and cache[key].get("lat") is None):
            continue
        try:
            cache[key] = lookup(session, name, address)
        except requests.RequestException as exc:
            failed += 1
            print(f"  ! {name}: {type(exc).__name__}: {exc}")
            continue
        looked_up += 1
        hit = cache[key]
        if hit.get("lat") is None:
            print(f"  - {name}: {hit['reason']}")
        else:
            print(f"  + {name} -> {hit['match']} ({hit['lat']}, {hit['lng']})")
    write_json(GEOCODE_FILE, dict(sorted(cache.items())))

    placed = 0
    for e in store["events"]:
        hit = cache.get(cache_key(e["venue"]["name"], e["venue"].get("address"))) or {}
        e["venue"]["lat"], e["venue"]["lng"] = hit.get("lat"), hit.get("lng")
        placed += hit.get("lat") is not None
    write_json(EVENTS_FILE, store)
    print(f"Looked up {looked_up} venue(s), {failed} failed; {placed} of {len(store['events'])} events have a position")
    return 1 if failed and not looked_up else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find map positions for event venues.")
    parser.add_argument("--retry", action="store_true", help="retry venues that found no match before")
    return run(parser.parse_args(argv).retry)


if __name__ == "__main__":
    sys.exit(main())
