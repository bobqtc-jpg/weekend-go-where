"""Choose what to suggest for a weekend: the picks, the rest of the weekend, what to book
ahead, and the best of the weekends after.

The web page (site/template.html) applies the same rules in its own script, so the page and
the weekly email suggest the same things. Change both together.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta

from .common import CONFIG_DIR, load_yaml
from .preview import FIT_RANK, classify, runs_on

MAX_PICKS = 6
LATER_WEEKENDS = 3
LATER_PICKS = 3
AHEAD_DAYS = 42
AHEAD_MAX = 8


def load_settings() -> dict:
    """The planning settings the page and the email use, with dates as ISO strings."""
    settings = load_yaml(CONFIG_DIR / "settings.yaml")
    planning, home = settings.get("planning", {}), settings.get("home", {})
    return {
        "limited_max_days": int(planning.get("limited_max_days", 42)),
        "last_chance_days": int(planning.get("last_chance_days", 14)),
        # YAML reads the date keys as dates; the page wants ISO strings.
        "public_holidays": {str(k): str(v) for k, v in (planning.get("public_holidays") or {}).items()},
        "home": {"label": home.get("label", "Home"), "lat": home.get("lat"), "lng": home.get("lng")},
    }


@dataclass
class Weekend:
    offset: int
    sat: date
    days: list[date]

    @property
    def first(self) -> date:
        return self.days[0]

    @property
    def last(self) -> date:
        return self.days[-1]


def weekend(today: date, holidays: dict[str, str], offset: int = 0) -> Weekend:
    """The weekend of the current week (on a Sunday, the one in progress), plus a Friday or
    Monday public holiday next to it. On a holiday Monday, that long weekend is still current."""
    weekday = today.weekday()
    if weekday == 6:
        sat = today - timedelta(days=1)
    elif weekday == 0 and today.isoformat() in holidays:
        sat = today - timedelta(days=2)
    else:
        sat = today + timedelta(days=5 - weekday)
    sat += timedelta(days=7 * offset)
    days = [sat, sat + timedelta(days=1)]
    if (sat - timedelta(days=1)).isoformat() in holidays:
        days.insert(0, sat - timedelta(days=1))
    if (sat + timedelta(days=2)).isoformat() in holidays:
        days.append(sat + timedelta(days=2))
    return Weekend(offset, sat, days)


def fit(event: dict) -> str:
    return event.get("fit") or "ok"


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = math.pi / 180
    d_lat, d_lng = (lat2 - lat1) * r, (lng2 - lng1) * r
    a = math.sin(d_lat / 2) ** 2 + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin(d_lng / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def has_position(event: dict) -> bool:
    return event["venue"].get("lat") is not None and event["venue"].get("lng") is not None


def upcoming(events: list[dict], today: date, home: dict) -> list[dict]:
    """Events that have not ended, each copied with `_km`: the straight-line distance from home,
    or None when the venue has no position."""
    out = []
    for e in events:
        if e["dates"]["end"] < today.isoformat():
            continue
        km = None
        if has_position(e) and home.get("lat") is not None:
            km = distance_km(home["lat"], home["lng"], e["venue"]["lat"], e["venue"]["lng"])
        out.append({**e, "_km": km})
    return out


def on_weekend(event: dict, wk: Weekend) -> bool:
    return any(runs_on(event, d) for d in wk.days)


def same_place(a: dict, b: dict) -> bool:
    if has_position(a) and has_position(b):
        return distance_km(a["venue"]["lat"], a["venue"]["lng"], b["venue"]["lat"], b["venue"]["lng"]) < 0.5

    def key(e: dict) -> str:
        return re.sub(r"\([^)]*\)", "", e["venue"]["name"]).split(",")[-1].strip().lower()

    return key(a) == key(b)


def safe_url(url: object) -> str | None:
    return url if isinstance(url, str) and re.match(r"https?://", url, re.I) else None


def fully_booked(event: dict) -> bool:
    return (event.get("booking") or {}).get("status") == "fully_booked"


def needs_booking(event: dict) -> bool:
    """Booking data is only reliable when there is a link: a ticketed workshop or show, or a registration."""
    b = event.get("booking") or {}
    if b.get("status") == "fully_booked" or not safe_url(b.get("url")):
        return False
    return b.get("status") == "registration_required" or (
        b.get("required") is True and event["category"] in ("workshop", "performance")
    )


def price_text(event: dict) -> tuple[str, bool]:
    """A short price label, and whether it counts as free."""
    c = event["cost"]
    text = c.get("price_text") or ""
    if c.get("is_free") is True:
        return "Free", True
    low = c.get("min_sgd")
    if isinstance(low, (int, float)) and low > 0:
        return (f"From ${int(low)}" if float(low).is_integer() else f"From ${low:.2f}"), False
    if re.search("free", text, re.I) and re.search(r"(singaporean|resident|\bprs?\b)", text, re.I):
        return "Free for residents", True
    if re.search("free", text, re.I):
        return "Free with conditions", False
    return ("Paid" if text else "Check price"), False


def pick_score(event: dict, wk: Weekend, settings: dict) -> int:
    """Higher for events that end soon, are new, say they suit toddlers, are free or are near home."""
    score = 0
    kind = classify(event, wk.sat, settings["limited_max_days"], settings["last_chance_days"])
    if kind in ("limited", "last_chance"):
        if event["dates"]["end"] <= wk.last.isoformat():
            score += 3
        elif kind == "last_chance":
            score += 2
        else:
            score += 1
    if event["dates"]["start"] >= (wk.first - timedelta(days=2)).isoformat() and kind != "weekly":
        score += 1  # new this weekend
    if event["audience"]["toddler_ok"] == "yes":
        score += 1
    if event["cost"].get("is_free") is True:
        score += 1
    km = event.get("_km")
    if km is not None:
        score += 2 if km <= 5 else 1 if km <= 10 else -1 if km > 15 else 0
    return score


def _km_or_far(event: dict) -> float:
    return event["_km"] if event.get("_km") is not None else 99


def picks_for(
    events: list[dict], wk: Weekend, settings: dict, limit: int = MAX_PICKS, exclude: set[str] | None = None
) -> list[dict]:
    """Great events first (only great ones when there are at least four), then by score and
    distance; at most one per place, never fully booked. `events` come from upcoming()."""
    exclude = exclude or set()
    pool = [
        e
        for e in events
        if on_weekend(e, wk) and fit(e) != "low" and not fully_booked(e) and e["id"] not in exclude
    ]
    pool.sort(key=lambda e: (FIT_RANK[fit(e)], -pick_score(e, wk, settings), _km_or_far(e), e["title"].casefold()))
    greats = [e for e in pool if fit(e) == "great"]
    out: list[dict] = []
    for e in greats if len(greats) >= 4 else pool:
        if len(out) >= limit:
            break
        if not any(same_place(q, e) for q in out):
            out.append(e)
    return out


def also_on(events: list[dict], wk: Weekend, picks: list[dict]) -> tuple[list[dict], int]:
    """The weekend's other events that suit a toddler (fully booked last, then by fit and
    distance), and how many were left out as not a toddler outing."""
    pick_ids = {e["id"] for e in picks}
    pool = [e for e in events if on_weekend(e, wk) and e["id"] not in pick_ids]
    fitting = [e for e in pool if fit(e) != "low"]
    fitting.sort(key=lambda e: (fully_booked(e), FIT_RANK[fit(e)], _km_or_far(e), e["title"].casefold()))
    return fitting, len(pool) - len(fitting)


def book_ahead(events: list[dict], today: date, settings: dict) -> list[dict]:
    """Events after this weekend and within six weeks that need booking, soonest first."""
    after = weekend(today, settings["public_holidays"]).last.isoformat()
    until = (today + timedelta(days=AHEAD_DAYS)).isoformat()
    items = [
        e for e in events if fit(e) != "low" and after < e["dates"]["start"] <= until and needs_booking(e)
    ]
    items.sort(key=lambda e: (e["dates"]["start"], FIT_RANK[fit(e)]))
    return items[:AHEAD_MAX]


def later_weekends(
    events: list[dict], wk: Weekend, today: date, settings: dict, picks: list[dict]
) -> list[tuple[Weekend, list[dict]]]:
    """The top few for each of the next weekends, never repeating an event already shown."""
    shown = {e["id"] for e in picks}
    out = []
    for offset in range(wk.offset + 1, wk.offset + 1 + LATER_WEEKENDS):
        w = weekend(today, settings["public_holidays"], offset)
        top = picks_for(events, w, settings, LATER_PICKS, shown)
        shown.update(e["id"] for e in top)
        out.append((w, top))
    return out
