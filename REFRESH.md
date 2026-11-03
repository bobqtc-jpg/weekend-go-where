# Weekly refresh runbook

This is the brief for the scheduled Claude Code session that refreshes the events
list every Thursday. It runs on the owner's Claude plan, so there is no API key:
the session reads the articles itself and writes the structured events.

## Steps

1. Set up: `python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'`
2. Fetch: `python -m refresh.fetch`
   - Changed articles go to `inbox/articles/` and are listed in `inbox/manifest.json`.
   - If every source fails, stop and report the errors. Do not touch `data/`.
   - **Muse email:** search Gmail with the `muse` query in `config/sources.yaml`. Take the newest match and
     never one whose subject starts with `[SAMPLE]`. Save its plain-text body to a file, then run
     `python -m refresh.add_article --source muse --title "<subject>" --url "https://mail.google.com/mail/#all/<thread id>" --published <YYYY-MM-DD> --text-file <file>`.
     If nothing matches, note it in the report and carry on.
3. Extract: for every key in `inbox/manifest.json`, read `inbox/articles/<key>.json`
   and write `inbox/extracted/<key>.json`: a JSON list of candidate events that
   follow the rules below. Write `[]` for an article with no qualifying events.
4. Merge: `python -m refresh.merge`. If it reports invalid candidates, fix those
   files and rerun until it passes. Use `--skip-invalid` only for a candidate that
   cannot be fixed from the article, and say so in the report.
5. Check: `python -m refresh.validate` and `pytest -q` must both pass.
6. Commit only `data/`, with the message `Weekly refresh YYYY-MM-DD`, and push.
7. Report: new, updated and expired counts, sources that failed, and anything you were unsure about.

## Extraction rules

- **One candidate per event:** a listing that covers several venues with their own dates becomes several candidates.
- **Dated happenings only:** include events that end on or after today. Skip permanent attractions, playgrounds, restaurants, deals, giveaways and term-long classes.
- **For families, in Singapore:** skip items aimed only at adults (dining promotions, buffets, school open houses, parenting talks) and anything outside Singapore.
- **Stated facts only:** use `null` (or `"unclear"`) instead of guessing.
- **Dates:** `YYYY-MM-DD`; a one-day event has `start` equal to `end`. When the article only says "this weekend", take the dates from its dated title, such as "(7 to 8 Nov 2026)", and say so in `notes`.
- **Missing dates:** apply these fixed rules and say which one you used in `notes`, so every run treats them the same way:
  - **No start ("now till 19 Sep 2027"):** start on the first day of the period the article covers (from its dated title), else its publish date.
  - **No end ("opens 3 Nov"):** end on the last day of the period the article covers, else 7 days after its publish date.
  - **Months only ("October to March"):** the first day of the first month to the last day of the last month.
  - **Recurring with no end ("every Saturday"):** one candidate for the period the article covers, with `days` set.
  - **No usable date at all:** skip it.
- **`dates.pattern`:** `recurring` for things that repeat on a schedule with no near end (weekly fire station visits, nightly light shows, monthly storytelling), `open_ended` when no end date is stated (so `end` is the placeholder from the rule above), otherwise `fixed`. This is what lets the app separate limited-time happenings from evergreen ones.
- **Permanent venues are places, not events:** skip indoor playgrounds, permanent museum galleries and parks in this step, even when an article lists them; the places directory covers them.
- **`days`:** the days the event runs within its date range; leave it empty when it runs every day or the article does not say.
- **`summary`:** one or two sentences in your own words, at most 280 characters. Never copy sentences from the article.
- **`audience.toddler_ok`:** `yes` when the stated ages include 2, or the event is billed for toddlers or all ages; `no` when the minimum age is 4 or more, or it is clearly for older children; otherwise `unclear`.
- **`cost`:** `is_free` is `true` only when the article says free; `min_sgd` is the cheapest stated price in SGD.
- **`booking`:** `url` is the registration or ticket link given in the article; `opens` only when the article states when registration opens; `status` is `open`, `registration_required` (spaces left) or `fully_booked` when stated, else `null`. Include fully booked events with that status, so the app can mark them.
- **Digests (the Muse email):** each item names its own link, so put it in the candidate's `source_url` (the first link when there are several). Skip the "Indoor backup" list: those are places, not events.
- **`venue`:** `region` is `central`, `east`, `north`, `north_east` or `west` from the venue's location, else `null`. Leave `lat` and `lng` as `null`.
- **`setting`:** `indoor`, `outdoor`, `mixed` or `unclear`.
- **Leave out** `id`, `sources`, `first_seen` and `last_seen`; `refresh.merge` adds them.

## Candidate shape

```json
{
  "title": "string",
  "summary": "string, own words, at most 280 characters",
  "category": "performance | workshop | festival | exhibition | play | nature | sport | market | holiday_programme | storytelling | other",
  "venue": {"name": "string", "address": "string or null", "region": "central | east | north | north_east | west | null", "lat": null, "lng": null},
  "dates": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "pattern": "fixed | recurring | open_ended", "times": "string or null", "days": ["sat", "sun"]},
  "audience": {"age_min": "number or null", "age_max": "number or null", "toddler_ok": "yes | no | unclear"},
  "cost": {"is_free": "true, false or null", "price_text": "string or null", "min_sgd": "number or null"},
  "booking": {"required": "true, false or null", "status": "open | registration_required | fully_booked | null", "url": "string or null", "opens": "YYYY-MM-DD or null"},
  "setting": "indoor | outdoor | mixed | unclear",
  "notes": "string or null",
  "source_url": "digests only: the item's own link"
}
```
