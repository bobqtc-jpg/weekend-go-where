"""Tests for event validation. Every name and URL here is made up."""
from datetime import date

import pytest

from refresh.validate import event_errors, load_validator

TODAY = date(2026, 11, 5)


@pytest.fixture(scope="module")
def validator():
    return load_validator("event.schema.json")


def make_event(**overrides):
    event = {
        "id": "ev_0123456789ab",
        "title": "Test Puppet Show",
        "summary": "A short puppet show that exists only in tests.",
        "category": "performance",
        "venue": {"name": "Test Venue", "address": None, "region": "east", "lat": None, "lng": None},
        "dates": {"start": "2026-11-07", "end": "2026-11-08", "times": "10am", "days": ["sat", "sun"]},
        "audience": {"age_min": 2, "age_max": 6, "toddler_ok": "yes"},
        "cost": {"is_free": True, "price_text": "Free", "min_sgd": None},
        "booking": {"required": False, "url": None, "opens": None},
        "setting": "indoor",
        "sources": [{"source_id": "test", "url": "https://example.com/a", "article_title": None, "published": None}],
        "first_seen": "2026-11-05",
        "last_seen": "2026-11-05",
        "notes": None,
    }
    event.update(overrides)
    return event


def test_valid_event_passes(validator):
    assert event_errors(make_event(), validator, TODAY) == []


def test_end_before_start_fails(validator):
    errors = event_errors(make_event(dates={"start": "2026-11-08", "end": "2026-11-07"}), validator, TODAY)
    assert any("end is before start" in e for e in errors)


def test_impossible_date_fails(validator):
    assert event_errors(make_event(dates={"start": "2026-02-30", "end": "2026-03-01"}), validator, TODAY)


def test_unknown_toddler_value_fails(validator):
    errors = event_errors(make_event(audience={"toddler_ok": "maybe"}), validator, TODAY)
    assert any("toddler_ok" in e for e in errors)


def test_booking_opening_after_end_fails(validator):
    booking = {"required": True, "url": "https://example.com/book", "opens": "2026-12-01"}
    errors = event_errors(make_event(booking=booking), validator, TODAY)
    assert any("opens after" in e for e in errors)


def test_unknown_booking_status_fails(validator):
    booking = {"required": True, "status": "almost full", "url": None, "opens": None}
    assert any("status" in e for e in event_errors(make_event(booking=booking), validator, TODAY))


def test_long_running_attraction_is_rejected(validator):
    errors = event_errors(make_event(dates={"start": "2026-01-01", "end": "2027-06-30"}), validator, TODAY)
    assert any("treat it as a place" in e for e in errors)


def test_non_http_url_fails(validator):
    event = make_event(sources=[{"source_id": "test", "url": "ftp://example.com/a"}])
    assert any("not http" in e for e in event_errors(event, validator, TODAY))
