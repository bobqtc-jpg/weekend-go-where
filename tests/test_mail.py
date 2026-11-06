"""Tests for the weekly email. Every name here is made up."""
from datetime import date

from refresh.mail import compose
from tests.test_plan import SETTINGS, THU, event

FORECAST = {
    "issued": "2026-11-05T11:30:00+08:00",
    "days": {
        d: {"summary": "Afternoon thundery showers", "text": "Thundery showers in the afternoon.", "low": 24, "high": 33}
        for d in ("2026-11-07", "2026-11-08", "2026-11-09")
    },
}


def store(*events):
    return {"updated": "2026-11-05", "events": list(events)}


def test_subject_holiday_and_weather_advice():
    message = compose(store(event("Bubble Morning")), SETTINGS, FORECAST, THU)
    assert message.subject == "Weekend go where? Sat 7 – Mon 9 Nov"
    assert "Long weekend: Monday is a public holiday (Deepavali)" in message.text
    assert "Go out in the morning" in message.html
    assert message.preheader.startswith("Bubble Morning")


def test_text_from_sources_is_escaped_and_unsafe_links_are_dropped():
    bad = event("<script>alert(1)</script> Bubbles", booking={"url": "javascript:alert(1)"})
    message = compose(store(bad), SETTINGS, FORECAST, THU)
    assert "<script" not in message.html
    assert "&lt;script&gt;" in message.html
    assert "javascript:" not in message.html


def test_low_fit_events_are_counted_but_not_shown():
    message = compose(store(event("Bubble Morning"), event("Wine Tasting", fit="low", lng=103.95)), SETTINGS, None, THU)
    assert "Wine Tasting" not in message.html
    assert "Left out: 1 event that is not really a toddler outing" in message.text
    assert "WEATHER" not in message.text  # no forecast, no weather section


def test_an_empty_weekend_still_builds():
    message = compose(store(), SETTINGS, None, date(2026, 11, 12))
    assert "Nothing good for a toddler is listed for this weekend yet." in message.text
