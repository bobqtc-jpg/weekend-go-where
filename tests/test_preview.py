"""Tests for the weekend preview. Every name here is made up."""
from datetime import date

from refresh.preview import classify, group_events, next_weekend, render, runs_on, weekend_events

SAT, SUN = date(2026, 11, 7), date(2026, 11, 8)


def event(title, start, end, days=(), toddler="yes", free=None, pattern=None):
    dates = {"start": start, "end": end, "days": list(days)}
    if pattern:
        dates["pattern"] = pattern
    return {
        "title": title,
        "dates": dates,
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


def test_low_fit_is_hidden_and_great_comes_first():
    ok = event("Ok Festival", "2026-11-07", "2026-11-07")
    ok["fit"] = "ok"
    great = event("Great Bubbles", "2026-11-07", "2026-11-07")
    great["fit"] = "great"
    low = event("Adult Workshop", "2026-11-07", "2026-11-07")
    low["fit"] = "low"
    picked = weekend_events([ok, great, low], SAT, SUN)
    assert [e["title"] for e in picked] == ["Great Bubbles", "Ok Festival"]
    assert len(weekend_events([ok, great, low], SAT, SUN, all_ages=True)) == 3


def test_classify_limited_last_chance_weekly_and_ongoing():
    assert classify(event("Two-day Fair", "2026-11-07", "2026-11-08"), SAT) == "limited"
    assert classify(event("Month-long Pop-up", "2026-10-09", "2026-11-09"), SAT) == "limited"
    assert classify(event("Long Exhibition Ending", "2026-06-06", "2026-11-11"), SAT) == "last_chance"
    assert classify(event("Long Exhibition", "2026-05-30", "2027-01-03"), SAT) == "ongoing"
    assert classify(event("Every Saturday", "2026-11-07", "2026-11-07", pattern="recurring"), SAT) == "weekly"
    assert classify(event("Opens This Week", "2026-11-03", "2026-11-08", pattern="open_ended"), SAT) == "ongoing"


def test_last_chance_window_counts_from_saturday():
    long_run = event("Ends In Two Weeks", "2026-08-01", "2026-11-20")
    assert classify(long_run, SAT) == "last_chance"  # 20 Nov is before 21 Nov
    assert classify(event("Ends In Three Weeks", "2026-08-01", "2026-11-21"), SAT) == "ongoing"


def test_groups_put_soonest_ending_limited_events_first():
    events = [
        event("Ends Sunday", "2026-11-01", "2026-11-08"),
        event("Ends Saturday", "2026-11-07", "2026-11-07"),
        event("Last Chance Exhibition", "2026-06-06", "2026-11-11"),
        event("Fire Station Visits", "2026-11-07", "2026-11-07", pattern="recurring"),
        event("Year-long Library", "2026-10-27", "2027-09-19"),
    ]
    groups = group_events(events, SAT, 42, 14)
    assert [e["title"] for _, e in groups["limited"]] == ["Ends Saturday", "Ends Sunday", "Last Chance Exhibition"]
    assert [e["title"] for _, e in groups["weekly"]] == ["Fire Station Visits"]
    assert [e["title"] for _, e in groups["ongoing"]] == ["Year-long Library"]
    text = render(events, SAT, SUN, 42, 14)
    assert "## Limited time (3)" in text and "last chance: ends 11 Nov" in text and "## Every week (1)" in text
