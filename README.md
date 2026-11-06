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
| Weekly Thursday run (scheduled task "Weekend events refresh") | Works; the 5 Nov 2026 rerun saved 143 events, cut to 125 after merging duplicates |
| Fit for a toddler (`fit` on every event) | Judged at extraction: great, ok or low; low is hidden by default (64 of 125 on 5 Nov) |
| Map positions (`refresh/geocode.py`, `data/geocode.json`) | OneMap search, cached; 116 of 125 events placed on 5 Nov |
| Weekend preview (`refresh/preview.py`) | Done |
| Muse's weekly Instagram digest by email (`refresh/add_article.py`) | Works; the 5 Nov run read the 4 Nov email through Gmail (read-only tools) |
| Places directory | Not started |
| Web page (`site/`) | Second version 5 Nov 2026: picks, map, weather, filters; private claude.ai preview; hosting not set up |
| Weekly email (`refresh/mail.py`, `refresh/plan.py`) | First sent 6 Nov 2026; scheduled task "Weekend email" sends it every Thursday at about 4:35pm SGT |

## Decisions

| Topic | Choice |
|---|---|
| Kids | One toddler; the default filter is "suits a 2-year-old" |
| Home | Marine Parade; MRT, bus and car all fine |
| Hosting | Private web app with a login limited to two emails; shared lists in v2 |
| Planning | Thursdays, by email, with the web page for more detail; no Telegram |
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

Everything is embedded in the page, so it needs no server and makes no requests. For the chosen
weekend (this one, or up to three ahead) it shows:

- **The days**, with NEA's forecast as it stood at build time. A Friday or Monday listed under
  `public_holidays` in `config/settings.yaml` joins the weekend.
- **Picks:** up to six `great` events, at most one per place, never fully booked. Ones that end
  this weekend, are near home, are free or say they suit toddlers rank higher.
- **A map** of Singapore (`site/singapore.json`, from geoBoundaries) with home, 5 km and 10 km
  rings, the numbered picks and the other events.
- **Also this weekend:** the rest of the `great` and `ok` events, nearest first, with filters for
  day, time of day, indoor, free and within 10 km. `low` events are behind a link.
- **Book ahead:** sessions and shows in the next six weeks that need booking online.
- **The weekends after:** the top three for each of the next three weekends.

Hosting is not set up yet. On Cloudflare Pages: connect this repo, build command
`pip install pyyaml && python3 site/build.py`, output directory `dist`. Every Thursday push of
`data/` then rebuilds the page. Cloudflare Access can limit it to two email addresses.

## The weekly email

`python -m refresh.mail` writes `dist/email.html`, `dist/email.txt` (its plain-text copy) and
`dist/email-subject.txt`. It uses the same rules as the page, from `refresh/plan.py`: the days
with NEA's forecast, up to six picks, up to eight more events for the weekend, what to book in
the next six weeks, and the top three for each of the next three weekends. The HTML has tables
and inline styles only, with no images or scripts, because mail apps drop most other CSS.

A second scheduled task, "Weekend email", runs every Thursday at about 4:35pm Singapore time,
after the 2:39pm refresh. It pulls `main`, runs `python -m refresh.mail` and sends the result
through the Gmail connector. Its only Gmail permission is sending: the event text it handles
comes from web pages, so it gets no way to read the inbox. The recipient is in the task's
settings, not in this repository.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest -q
python -m refresh.fetch      # needs network access to the source sites
python -m refresh.titles     # saved events, so extraction can reuse their titles
python -m refresh.merge
python -m refresh.geocode    # map positions for new venues, from OneMap
python -m refresh.validate
python -m refresh.preview    # the coming weekend's events, best fit first
python site/build.py         # the web page, into dist/
python -m refresh.mail       # the weekly email, into dist/
```

## Network access

The cloud environment that runs the refresh must allow these hosts:

- **Sources:** `www.sassymamasg.com`, `www.bykido.com`, `www.littledayout.com`, `honeykidsasia.com`, `www.honeykidsasia.com`, `sunnycitykids.beehiiv.com`
- **Maps and parks:** `www.onemap.gov.sg`, `data.gov.sg`, `api-open.data.gov.sg`, `api-production.data.gov.sg`, `www.nparks.gov.sg`
