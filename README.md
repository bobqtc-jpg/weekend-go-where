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
| Fetchers for five sources (`refresh/fetch.py`, `config/sources.yaml`) | All five work as of 5 Nov 2026; Little Day Out now reads its RSS feed |
| Weekly Thursday run (scheduled task "Weekend events refresh") | First run on 5 Nov 2026 stopped before saving because of a merge bug, since fixed |
| Weekend preview (`refresh/preview.py`) | Done |
| Muse's weekly Instagram digest by email (`refresh/add_article.py`) | Works; the 5 Nov run read the 4 Nov email through Gmail (read-only tools) |
| Places directory | Not started |
| Web page (`site/`) | First version built 5 Nov 2026; private claude.ai preview; hosting not set up |

## Decisions

| Topic | Choice |
|---|---|
| Kids | One toddler; the default filter is "suits a 2-year-old" |
| Home | Marine Parade; MRT, bus and car all fine |
| Hosting | Private web app with a login limited to two emails; shared lists in v2 |
| Planning | Thursdays, in the app; no Telegram or digest |
| Claude | The owner's Max plan, through a scheduled Claude Code task; no API key |
| Sources | Sassy Mama, Little Day Out, ByKido, Honeykids Asia, Sunny City Kids, and Muse's Instagram digest (emailed Wednesday evenings, read through Gmail). Time Out was dropped: its new site refuses automated readers |
| Filters | No dietary filter; paid indoor playgrounds included |
| Stack | Python refresh job; TypeScript web app |

## How the weekly refresh works

1. A scheduled Claude Code task starts a fresh session every Thursday afternoon, Singapore time.
2. The session follows [REFRESH.md](REFRESH.md): fetch, extract the events itself, merge, validate, push `data/`.
3. The web app reads `data/events.json` and `data/places.json`.

## How the weekend view is grouped

| Group | What goes in it |
|---|---|
| Limited time | One-offs and runs of up to 6 weeks, plus longer runs in their last two weekends ("last chance"); soonest ending first |
| Every week | Things that repeat with no near end, such as fire station visits and beach movies |
| Ongoing | Runs longer than 6 weeks, and anything with no stated end |
| Places (directory) | Permanent venues: playgrounds, indoor playgrounds, restaurants; not events at all |

The thresholds live in `config/settings.yaml` (`limited_max_days`, `last_chance_days`); the
grouping reads each event's `dates.pattern` (`fixed`, `recurring` or `open_ended`).

## The web page

`python site/build.py` turns `site/template.html` and the data into one self-contained page:

- `dist/index.html`: the full page, for hosting.
- `dist/artifact.html`: the same page without the document wrapper, for a private claude.ai preview.

The events are embedded in the page, so it needs no server. It shows this weekend, next weekend
and the coming four weeks, with filters for toddler-confirmed, free, indoor and east-side events.
A Friday or Monday listed under `public_holidays` in `config/settings.yaml` joins the weekend.

Hosting is not set up yet. On Cloudflare Pages: connect this repo, build command
`pip install pyyaml && python3 site/build.py`, output directory `dist`. Every Thursday push of
`data/` then rebuilds the page. Cloudflare Access can limit it to two email addresses.

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

- **Sources:** `www.sassymamasg.com`, `www.bykido.com`, `www.littledayout.com`, `honeykidsasia.com`, `www.honeykidsasia.com`, `sunnycitykids.beehiiv.com`
- **Maps and parks:** `www.onemap.gov.sg`, `data.gov.sg`, `api-open.data.gov.sg`, `api-production.data.gov.sg`, `www.nparks.gov.sg`
