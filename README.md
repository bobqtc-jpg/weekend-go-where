# Weekend Go Where

A private weekend planner for one Singapore family. Every Thursday it collects
kid-friendly events from parenting sites; the app shows them next to a directory
of playgrounds and kid-friendly restaurants, filtered for a toddler and sorted by
distance from Marine Parade.

## Status

| Piece | State |
|---|---|
| Event and place formats (`schema/`) | Done |
| Merge and validation (`refresh/merge.py`, `refresh/validate.py`) | Done; tested offline |
| Fetchers for six sources (`refresh/fetch.py`, `config/sources.yaml`) | Sassy Mama and ByKido tested live on 3 Nov 2026; the other four not yet |
| Weekend preview (`refresh/preview.py`) | Done |
| Weekly refresh on the Max plan ([REFRESH.md](REFRESH.md)) | Runbook written; scheduled task not created yet |
| Places directory | Not started |
| Web app | Not started; waits on a successful test pull |

## Decisions

| Topic | Choice |
|---|---|
| Kids | One toddler; the default filter is "suits a 2-year-old" |
| Home | Marine Parade; MRT, bus and car all fine |
| Hosting | Private web app with a login limited to two emails; shared lists in v2 |
| Planning | Thursdays, in the app; no Telegram or digest |
| Claude | The owner's Max plan, through a scheduled Claude Code task; no API key |
| Sources | Sassy Mama, Little Day Out, ByKido, Honeykids Asia, Sunny City Kids, Time Out |
| Filters | No dietary filter; paid indoor playgrounds included |
| Stack | Python refresh job; TypeScript web app |

## How the weekly refresh works

1. A scheduled Claude Code task starts a fresh session every Thursday afternoon, Singapore time.
2. The session follows [REFRESH.md](REFRESH.md): fetch, extract the events itself, merge, validate, push `data/`.
3. The web app reads `data/events.json` and `data/places.json`.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest -q
python -m refresh.fetch      # needs network access to the source sites
python -m refresh.merge
python -m refresh.validate
python -m refresh.preview    # the coming weekend's events, toddler-friendly first
```

## Network access

The cloud environment that runs the refresh must allow these hosts:

- **Sources:** `www.sassymamasg.com`, `www.bykido.com`, `www.littledayout.com`, `honeykidsasia.com`, `www.honeykidsasia.com`, `sunnycitykids.beehiiv.com`, `www.timeout.com`
- **Maps and parks:** `www.onemap.gov.sg`, `data.gov.sg`, `api-open.data.gov.sg`, `api-production.data.gov.sg`, `www.nparks.gov.sg`
