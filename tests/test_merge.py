"""Tests for merging extracted events. Every name and URL here is made up."""
from datetime import date

import pytest

from refresh.merge import merge, similarity
from refresh.validate import load_validator

TODAY = date(2026, 11, 5)


@pytest.fixture(scope="module")
def validator():
    return load_validator("event.schema.json")


def candidate(title="Test Bubble Show", venue="Test Mall Atrium", start="2026-11-07", end="2026-11-08"):
    """A candidate as the refresh session would write it."""
    return {
        "title": title,
        "summary": "A made-up bubble show used to test merging.",
        "category": "performance",
        "venue": {"name": venue, "address": None, "region": None, "lat": None, "lng": None},
        "dates": {"start": start, "end": end, "times": None, "days": []},
        "audience": {"age_min": None, "age_max": None, "toddler_ok": "unclear"},
        "cost": {"is_free": None, "price_text": None, "min_sgd": None},
        "setting": "unclear",
        "notes": None,
    }


def article(key):
    return {
        "source_id": key.split("__")[0],
        "url": f"https://example.com/{key}",
        "title": f"Article {key}",
        "published": "2026-11-05",
        "hash": "0" * 16,
    }


def run(extracted, validator, existing=(), today=TODAY, keep_days=7):
    manifest = {key: article(key) for key in extracted}
    return merge(list(existing), manifest, extracted, today, keep_days, validator)


def test_new_event_gets_id_source_and_dates(validator):
    events, report = run({"a__one": [candidate()]}, validator)
    assert (report.new, report.errors) == (1, [])
    (event,) = events
    assert event["id"].startswith("ev_")
    assert event["sources"][0]["url"] == "https://example.com/a__one"
    assert event["first_seen"] == event["last_seen"] == "2026-11-05"


def test_same_event_from_two_sources_is_folded(validator):
    second = candidate(title="The Test Bubble Show!")
    second["cost"] = {"is_free": True, "price_text": "Free", "min_sgd": None}
    events, report = run({"a__one": [candidate()], "b__two": [second]}, validator)
    assert (report.new, report.updated) == (1, 1)
    (event,) = events
    assert len(event["sources"]) == 2
    assert event["cost"]["is_free"] is True  # filled in from the second source


def test_same_title_on_other_dates_stays_separate(validator):
    events, _ = run({"a__one": [candidate(), candidate(start="2026-12-12", end="2026-12-13")]}, validator)
    assert len(events) == 2


def test_inferred_start_is_widened_without_a_note(validator):
    # One source says "now till 30 Nov" (start inferred), another gives the full run.
    inferred_start = candidate(start="2026-11-07", end="2026-11-30")
    explicit = candidate(start="2026-10-27", end="2026-11-30")
    events, _ = run({"a__one": [inferred_start], "b__two": [explicit]}, validator)
    (event,) = events
    assert (event["dates"]["start"], event["dates"]["end"]) == ("2026-10-27", "2026-11-30")
    assert event["notes"] is None


def test_clashing_end_dates_are_widened_and_noted(validator):
    events, _ = run({"a__one": [candidate(end="2026-11-15")], "b__two": [candidate(end="2026-11-22")]}, validator)
    (event,) = events
    assert event["dates"]["end"] == "2026-11-22"
    assert event["notes"] == "Sources differ on the end date: 2026-11-15 vs 2026-11-22."


def test_placeholder_ends_add_no_notes(validator):
    # An event with no stated end gets a different placeholder end every week.
    weeks = []
    for i, end in enumerate(["2026-11-08", "2026-11-09", "2026-11-10"]):
        c = candidate(start="2026-11-03", end=end)
        c["dates"]["pattern"] = "open_ended"
        weeks.append((f"w{i}__glow", c))
    events, _ = run({key: [c] for key, c in weeks}, validator)
    (event,) = events
    assert event["notes"] is None


def test_notes_never_exceed_the_schema_limit(validator):
    long_notes = candidate(end="2026-11-15")
    long_notes["notes"] = "x" * 390
    events, report = run(
        {"a__one": [long_notes], "b__two": [candidate(end="2026-11-22")], "c__three": [candidate(end="2026-11-29")]},
        validator,
    )
    (event,) = events
    assert report.errors == []
    assert len(event["notes"]) <= 400
    assert event["notes"].endswith("Sources differ on the end date: 2026-11-22 vs 2026-11-29.")


def test_stated_end_replaces_open_ended_placeholder(validator):
    opening = candidate(start="2026-11-03", end="2026-11-08")
    opening["dates"]["pattern"] = "open_ended"
    full_run = candidate(start="2026-11-03", end="2027-03-31")
    full_run["dates"]["pattern"] = "fixed"
    events, _ = run({"a__one": [opening], "b__two": [full_run]}, validator)
    (event,) = events
    assert (event["dates"]["end"], event["dates"]["pattern"]) == ("2027-03-31", "fixed")


def test_recurring_beats_fixed_when_sources_disagree(validator):
    weekly = candidate()
    weekly["dates"]["pattern"] = "recurring"
    one_off = candidate()
    one_off["dates"]["pattern"] = "fixed"
    events, _ = run({"a__one": [one_off], "b__two": [weekly]}, validator)
    assert events[0]["dates"]["pattern"] == "recurring"


def test_rerunning_the_same_article_does_not_duplicate_sources(validator):
    events, _ = run({"a__one": [candidate()]}, validator)
    events, report = run({"a__one": [candidate()]}, validator, existing=events)
    assert report.updated == 1
    assert len(events[0]["sources"]) == 1


def test_ended_events_expire_after_grace_period(validator):
    early = date(2026, 10, 19)
    events, _ = run(
        {"a__one": [candidate(start="2026-10-20", end="2026-10-25")], "b__two": [candidate(title="Other Show", start="2026-10-31", end="2026-11-01")]},
        validator,
        today=early,
    )
    kept, report = merge(events, {}, {}, TODAY, 7, validator)
    assert report.expired == 1
    assert [e["title"] for e in kept] == ["Other Show"]


def test_past_candidates_are_skipped(validator):
    events, report = run({"a__one": [candidate(start="2026-10-01", end="2026-10-02")]}, validator)
    assert events == [] and report.skipped_past == 1


def test_invalid_candidate_is_reported(validator):
    bad = candidate()
    bad["setting"] = "underwater"
    events, report = run({"a__one": [bad]}, validator)
    assert events == [] and report.errors


def test_missing_extraction_is_reported(validator):
    _, report = merge([], {"a__one": article("a__one")}, {"a__one": None}, TODAY, 7, validator)
    assert report.missing == ["a__one"]


def test_digest_items_link_to_their_own_page(validator):
    item = candidate()
    item["source_url"] = "https://example.com/p/abc"
    item["booking"] = {"required": True, "status": "fully_booked", "url": None, "opens": None}
    events, report = run({"muse__digest": [item]}, validator)
    assert report.errors == []
    (event,) = events
    assert event["sources"][0] == {
        "source_id": "muse",
        "url": "https://example.com/p/abc",
        "article_title": "Article muse__digest",
        "published": "2026-11-05",
    }
    assert "source_url" not in event and event["booking"]["status"] == "fully_booked"


def test_similarity_ignores_case_and_punctuation():
    assert similarity("Test Bubble Show!", "test bubble show") == 1.0
