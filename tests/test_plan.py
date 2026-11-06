"""Tests for the weekend plan: picks, book ahead and later weekends. Every name here is made up."""
from datetime import date

from refresh import plan
from refresh.common import stable_id

HOLIDAYS = {"2026-11-09": "Deepavali (observed)"}
SETTINGS = {"limited_max_days": 42, "last_chance_days": 14, "public_holidays": HOLIDAYS,
            "home": {"label": "Home", "lat": 1.30, "lng": 103.90}}
THU = date(2026, 11, 5)


def event(title, start="2026-11-07", end="2026-11-08", fit="great", lat=1.30, lng=103.91, booking=None, **cost):
    return {
        "id": stable_id("ev", title),
        "title": title,
        "summary": "A made-up event for testing.",
        "fit": fit,
        "category": "workshop",
        "venue": {"name": f"{title} Hall", "lat": lat, "lng": lng},
        "dates": {"start": start, "end": end},
        "audience": {"toddler_ok": "yes"},
        "cost": {"is_free": cost.get("is_free"), "price_text": cost.get("price_text"), "min_sgd": cost.get("min_sgd")},
        "booking": booking or {},
        "setting": "indoor",
        "sources": [{"source_id": "test", "url": "https://example.com/a"}],
    }


def titles(events):
    return [e["title"] for e in events]


def test_weekend_adds_a_holiday_monday():
    wk = plan.weekend(THU, HOLIDAYS)
    assert wk.days == [date(2026, 11, 7), date(2026, 11, 8), date(2026, 11, 9)]


def test_on_a_holiday_monday_the_long_weekend_is_still_current():
    assert plan.weekend(date(2026, 11, 9), HOLIDAYS).first == date(2026, 11, 7)
    assert plan.weekend(date(2026, 11, 12), HOLIDAYS).days == [date(2026, 11, 14), date(2026, 11, 15)]


def test_picks_leave_out_low_fit_and_fully_booked():
    events = plan.upcoming(
        [
            event("Bubble Morning"),
            event("Adult Talk", fit="low", lng=103.95),
            event("Full Class", lng=103.85, booking={"status": "fully_booked"}),
        ],
        THU,
        SETTINGS["home"],
    )
    assert titles(plan.picks_for(events, plan.weekend(THU, HOLIDAYS), SETTINGS)) == ["Bubble Morning"]


def test_picks_keep_one_per_place_and_only_great_ones_when_there_are_four():
    events = plan.upcoming(
        [
            event("Train Ride", lng=103.91),
            event("Train Shop", lng=103.9101),  # about 10 m from the ride
            event("Soft Play", lng=103.85),
            event("Animal Farm", lng=103.80),
            event("Water Park", lng=103.75),
            event("Okay Fair", fit="ok", lng=103.905),
        ],
        THU,
        SETTINGS["home"],
    )
    picks = titles(plan.picks_for(events, plan.weekend(THU, HOLIDAYS), SETTINGS))
    assert len(picks) == 4 and "Okay Fair" not in picks
    assert ("Train Ride" in picks) != ("Train Shop" in picks)


def test_book_ahead_needs_a_booking_link():
    linked = event("Clay Class", "2026-11-21", "2026-11-21",
                   booking={"status": "registration_required", "url": "https://example.com/book"})
    unlinked = event("Paint Class", "2026-11-21", "2026-11-21", booking={"status": "registration_required"})
    events = plan.upcoming([linked, unlinked], THU, SETTINGS["home"])
    assert titles(plan.book_ahead(events, THU, SETTINGS)) == ["Clay Class"]


def test_later_weekends_never_repeat_an_event():
    events = plan.upcoming(
        [event("Long Show", "2026-11-01", "2026-11-30"), event("Next Fair", "2026-11-14", "2026-11-15")],
        THU,
        SETTINGS["home"],
    )
    wk = plan.weekend(THU, HOLIDAYS)
    picks = plan.picks_for(events, wk, SETTINGS)
    later = plan.later_weekends(events, wk, THU, SETTINGS, picks)
    shown = titles(picks) + [t for _, top in later for t in titles(top)]
    assert sorted(shown) == ["Long Show", "Next Fair"]


def test_price_labels():
    assert plan.price_text(event("A", is_free=True)) == ("Free", True)
    assert plan.price_text(event("B", min_sgd=7.5)) == ("From $7.50", False)
    assert plan.price_text(event("C", price_text="Free for Singaporeans and PRs")) == ("Free for residents", True)
    assert plan.price_text(event("D", price_text="Free with a $30 spend")) == ("Free with conditions", False)
    assert plan.price_text(event("E")) == ("Check price", False)
