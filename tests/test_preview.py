"""Tests for the weekend preview. Every name here is made up."""
from datetime import date

from refresh.preview import next_weekend, runs_on, weekend_events


def event(title, start, end, days=(), toddler="yes", free=None):
    return {
        "title": title,
        "dates": {"start": start, "end": end, "days": list(days)},
        "audience": {"toddler_ok": toddler},
        "cost": {"is_free": free},
        "venue": {"name": "Test Venue"},
        "setting": "indoor",
        "sources": [{"source_id": "test", "url": "https://example.com"}],
    }


def test_next_weekend_from_a_weekday():
    assert next_weekend(date(2026, 11, 3)) == (date(2026, 11, 7), date(2026, 11, 8))


def test_next_weekend_on_saturday_and_sunday():
    assert next_weekend(date(2026, 11, 7)) == (date(2026, 11, 7), date(2026, 11, 8))
    assert next_weekend(date(2026, 11, 8)) == (date(2026, 11, 7), date(2026, 11, 8))


def test_runs_on_respects_listed_days():
    weekdays_only = event("Weekday Class", "2026-11-01", "2026-11-30", days=["mon", "tue"])
    assert not runs_on(weekdays_only, date(2026, 11, 7))
    assert runs_on(event("Daily Show", "2026-11-01", "2026-11-30"), date(2026, 11, 7))


def test_weekend_events_filters_and_orders():
    events = [
        event("Paid Toddler Show", "2026-11-07", "2026-11-07", free=False),
        event("Free Toddler Show", "2026-11-08", "2026-11-08", free=True),
        event("Teen Workshop", "2026-11-07", "2026-11-08", toddler="no"),
        event("Maybe Show", "2026-11-07", "2026-11-07", toddler="unclear"),
        event("Next Week", "2026-11-14", "2026-11-15"),
    ]
    picked = weekend_events(events, date(2026, 11, 7), date(2026, 11, 8))
    assert [e["title"] for e in picked] == ["Free Toddler Show", "Paid Toddler Show", "Maybe Show"]
    everything = weekend_events(events, date(2026, 11, 7), date(2026, 11, 8), all_ages=True)
    assert "Teen Workshop" in [e["title"] for e in everything]
