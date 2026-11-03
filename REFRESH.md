# Weekly refresh runbook

This is the brief for the scheduled Claude Code session that refreshes the events
list every Thursday. It runs on the owner's Claude plan, so there is no API key:
the session reads the articles itself and writes the structured events.

## Steps

1. Set up: `python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'`
2. Fetch: `python -m refresh.fetch`
   - Changed articles go to `inbox/articles/` and are listed in `inbox/manifest.json`.
   - If every source fails, stop and report the errors. Do not touch `data/`.
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
- **`days`:** the days the event runs within its date range; leave it empty when it runs every day or the article does not say.
- **`summary`:** one or two sentences in your own words, at most 280 characters. Never copy sentences from the article.
- **`audience.toddler_ok`:** `yes` when the stated ages include 2, or the event is billed for toddlers or all ages; `no` when the minimum age is 4 or more, or it is clearly for older children; otherwise `unclear`.
- **`cost`:** `is_free` is `true` only when the article says free; `min_sgd` is the cheapest stated price in SGD.
- **`booking`:** `url` is the registration or ticket link given in the article; `opens` only when the article states when registration opens.
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
  "dates": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "times": "string or null", "days": ["sat", "sun"]},
  "audience": {"age_min": "number or null", "age_max": "number or null", "toddler_ok": "yes | no | unclear"},
  "cost": {"is_free": "true, false or null", "price_text": "string or null", "min_sgd": "number or null"},
  "booking": {"required": "true, false or null", "url": "string or null", "opens": "YYYY-MM-DD or null"},
  "setting": "indoor | outdoor | mixed | unclear",
  "notes": "string or null"
}
```
