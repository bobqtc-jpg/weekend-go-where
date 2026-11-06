"""Write the weekly email: this weekend's picks with NEA's forecast, the rest of the weekend,
what to book ahead and the best of the weekends after.

Usage:
    python -m refresh.mail                    # as of today
    python -m refresh.mail --date 2026-11-05  # as if sent on another day

Writes dist/email.html (the message), dist/email.txt (its plain-text copy) and
dist/email-subject.txt, and prints the subject. What it suggests comes from refresh/plan.py,
the same rules the web page uses. The HTML has tables and inline styles only, because Gmail
and other mail apps drop most of the CSS a web page relies on, and no images or scripts.
"""
from __future__ import annotations

import argparse
import html
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import plan
from .common import EVENTS_FILE, ROOT, load_json, sg_today
from .preview import classify, runs_on
from .weather import forecast, wet_afternoons

DIST = ROOT / "dist"
ALSO_MAX = 8
SOURCE_NAMES = {
    "sassymama": "Sassy Mama", "bykido": "ByKido", "littledayout": "Little Day Out", "honeykids": "Honeykids",
    "sunnycitykids": "Sunny City Kids", "timeout": "Time Out", "muse": "Muse (Instagram)",
}
SETTING = {"indoor": "Indoor", "outdoor": "Outdoor", "mixed": "Indoor and outdoor"}
ADVICE = "Showers are forecast most afternoons. Go out in the morning, and keep indoor plans for after lunch."
NOT_TODDLER = "(adult workshops, shopping markets, races, shows for older children)"

# The web page's light colours.
BG, SURFACE, INK, MUTED, LINE = "#EDF2F0", "#FFFFFF", "#15272B", "#55686C", "#D3DEDB"
TEAL, SUN, SUN_INK, GOOD, BAD = "#0C6868", "#F5B800", "#382A00", "#1D7439", "#B0261D"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
CHIP = {"free": ("#DDF0E2", GOOD), "plain": (BG, INK), "soon": ("#FFF1C2", "#5C4300"), "book": ("#FBE6CF", "#8A4B00")}
META = f"font-size:14px;line-height:1.45;color:{MUTED}"


@dataclass
class Message:
    subject: str
    preheader: str
    html: str
    text: str


# Wording shared by the HTML and the text copy.

def fmt(d: date, year: int) -> str:
    """'7 Nov', or '19 Sep 2027' when the year differs from `year`."""
    return f"{d.day} {d:%b}" + ("" if d.year == year else f" {d.year}")


def span(wk: plan.Weekend, year: int) -> str:
    """'Sat 7 – Mon 9 Nov', or 'Sat 31 Oct – Sun 1 Nov'."""
    first, last = wk.first, wk.last
    month = "" if first.month == last.month else f" {first:%b}"
    return f"{first:%a} {first.day}{month} – {last:%a} {fmt(last, year)}"


def clock(dt: datetime) -> str:
    return f"{dt:%a} {dt.day} {dt:%b}, {dt.hour % 12 or 12}:{dt.minute:02d}{'am' if dt.hour < 12 else 'pm'}"


def joined(items: list[str]) -> str:
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


def km_text(e: dict) -> str | None:
    km = e.get("_km")
    if km is None:
        return None
    return f"{km:.1f} km" if km < 10 else f"{int(km + 0.5)} km"


def days_text(e: dict, wk: plan.Weekend) -> str:
    on = [f"{d:%a}" for d in wk.days if runs_on(e, d)]
    if len(on) == len(wk.days) and len(on) > 1:
        return "All weekend"
    return f"{on[0]} only" if len(on) == 1 else joined(on)


def timing(e: dict, wk: plan.Weekend, settings: dict) -> tuple[str, bool] | None:
    """When the run ends, and whether that is soon. None when the source gives no end."""
    kind = classify(e, wk.sat, settings["limited_max_days"], settings["last_chance_days"])
    if kind == "weekly":
        return "Every week", False
    if e["dates"].get("pattern") == "open_ended":
        return None
    start, end = date.fromisoformat(e["dates"]["start"]), date.fromisoformat(e["dates"]["end"])
    if wk.first <= end <= wk.last:
        return ("One day only" if start == end else f"Ends {end:%a}"), True
    if kind == "last_chance":
        return f"Last chance: ends {fmt(end, wk.sat.year)}", True
    return f"Until {fmt(end, wk.sat.year)}", False


def age_text(e: dict) -> str | None:
    a = e["audience"]
    if a["toddler_ok"] == "yes":
        return "Toddler OK"
    if a.get("age_min") is not None and a.get("age_max") is not None:
        return f"Ages {a['age_min']:g}–{a['age_max']:g}"
    if a.get("age_min") is not None:
        return f"Ages {a['age_min']:g}+"
    return None


def price_detail(e: dict) -> str | None:
    """The source's own price wording, when the short label leaves out an amount or a condition."""
    label, _ = plan.price_text(e)
    text = (e["cost"].get("price_text") or "").strip()
    return None if label in ("Free", "Free for residents") or not text else text


def links(e: dict) -> list[tuple[str, str]]:
    """(label, url) pairs: the booking page, then the first source."""
    out = []
    book = plan.safe_url((e.get("booking") or {}).get("url"))
    if book:
        out.append(("Book or register", book))
    for s in e["sources"]:
        url = plan.safe_url(s.get("url"))
        if url:
            out.append((f"From {SOURCE_NAMES.get(s['source_id'], s['source_id'])}", url))
            break
    return out


def main_link(e: dict) -> str | None:
    """The best single page for an event: its booking page, else its first source."""
    found = links(e)
    return found[0][1] if found else None


def weather_icon(f: dict) -> str:
    t = (f["text"] + " " + f["summary"]).lower()
    if "thunder" in t:
        return "⛈️"
    if "shower" in t or "rain" in t:
        return "\U0001f327️"
    if "cloud" in t or "haz" in t:
        return "⛅"
    return "☀️"


def holiday_line(wk: plan.Weekend, holidays: dict[str, str]) -> str | None:
    names = [(d, holidays[d.isoformat()]) for d in wk.days if d.isoformat() in holidays]
    if not names:
        return None
    d, name = names[0]
    return f"Long weekend: {d:%A} is a public holiday ({name.replace('(observed)', '').strip()})"


# HTML pieces. Every value from the data goes through esc(); links only ever carry http(s) URLs.

def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def a(url: str, text: str, color: str = TEAL) -> str:
    return f'<a href="{esc(url)}" style="color:{color};font-weight:600">{esc(text)}</a>'


def chip(text: str, kind: str) -> str:
    bg, fg = CHIP[kind]
    return (
        f'<span style="display:inline-block;margin:0 2px 4px 0;padding:2px 8px;border-radius:9px;background:{bg};'
        f'color:{fg};font-size:12px;font-weight:600">{esc(text)}</span>'
    )


def spacer(px: int) -> str:
    return f'<tr><td style="height:{px}px;line-height:{px}px;font-size:0">&nbsp;</td></tr>'


def card(inner: str, padding: str = "16px") -> str:
    return f'<tr><td style="background:{SURFACE};border-radius:14px;padding:{padding}">{inner}</td></tr>' + spacer(10)


def table(rows: str) -> str:
    return f'<table width="100%" cellpadding="0" cellspacing="0">{rows}</table>'


def heading(title: str, note: str | None = None) -> str:
    sub = f'<div style="margin-top:2px;{META}">{esc(note)}</div>' if note else ""
    return (
        f'<tr><td style="padding:18px 4px 10px"><div style="font-size:13px;font-weight:700;letter-spacing:.08em;'
        f'text-transform:uppercase;color:{TEAL}">{esc(title)}</div>{sub}</td></tr>'
    )


def where_html(e: dict) -> str:
    km = km_text(e)
    return esc(e["venue"]["name"]) + (f' · <span style="white-space:nowrap">{esc(km)}</span>' if km else "")


def pick_html(n: int, e: dict, wk: plan.Weekend, settings: dict) -> str:
    when = days_text(e, wk) + (f" · {e['dates']['times']}" if e["dates"].get("times") else "")
    label, free = plan.price_text(e)
    chips = [chip(label, "free" if free else "plain")]
    ends = timing(e, wk, settings)
    if ends:
        chips.append(chip(ends[0], "soon" if ends[1] else "plain"))
    if plan.needs_booking(e):
        chips.append(chip("Book ahead", "book"))
    age = age_text(e)
    if age:
        chips.append(chip(age, "free" if age == "Toddler OK" else "plain"))
    setting = f" · {SETTING[e['setting']]}" if e["setting"] in SETTING else ""
    detail = price_detail(e)
    body = (
        f'<div style="font-size:17px;font-weight:700;line-height:1.3;color:{INK}">{esc(e["title"])}</div>'
        f'<div style="{META};margin-top:4px">{esc(when)}</div>'
        f'<div style="{META}">{where_html(e)}{setting}</div>'
        f'<div style="margin-top:8px">{"".join(chips)}</div>'
        f'<div style="margin-top:2px;font-size:15px;line-height:1.5;color:{INK}">{esc(e["summary"])}</div>'
        + (f'<div style="{META};margin-top:6px">Price: {esc(detail)}</div>' if detail else "")
        + f'<div style="margin-top:8px;font-size:14px;line-height:1.7">'
        + " &nbsp;·&nbsp; ".join(a(url, text) for text, url in links(e))
        + "</div>"
    )
    badge = (
        f'<div style="width:28px;height:28px;line-height:28px;border-radius:14px;background:{SUN};color:{SUN_INK};'
        f'text-align:center;font-size:15px;font-weight:800">{n}</div>'
    )
    return card(table(f'<tr><td valign="top" style="width:40px">{badge}</td><td valign="top">{body}</td></tr>'))


def row_html(e: dict, first: bool, meta: list[str], lead: str = "") -> str:
    """One event in a list: its title, linked to its best page, over a line of details."""
    url = main_link(e)
    title = a(url, e["title"], INK) if url else esc(e["title"])
    border = "" if first else f"border-top:1px solid {LINE};"
    text = (
        f'<div style="font-size:15px;font-weight:600;line-height:1.35;color:{INK}">{title}</div>'
        f'<div style="{META};margin-top:2px">{" · ".join(meta)}</div>'
    )
    if lead:
        text = table(f'<tr><td valign="top" style="width:56px">{lead}</td><td valign="top">{text}</td></tr>')
    return f'<tr><td style="{border}padding:10px 0">{text}</td></tr>'


def price_html(e: dict) -> str:
    label, free = plan.price_text(e)
    return f'<span style="color:{GOOD if free else MUTED};font-weight:600">{esc(label)}</span>'


def date_box(d: date) -> str:
    bg, fg = CHIP["soon"]
    return (
        f'<div style="width:44px;padding:4px 0;border-radius:10px;background:{bg};color:{fg};text-align:center">'
        f'<div style="font-size:18px;font-weight:800;line-height:1.1">{d.day}</div>'
        f'<div style="font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase">{d:%b}</div></div>'
    )


def weather_html(wk: plan.Weekend, fc: dict | None, today: date) -> str:
    if not fc:
        return ""
    cells = []
    for d in wk.days:
        f = fc["days"].get(d.isoformat())
        top = f'<div style="font-size:13px;font-weight:700;color:{INK}">{d:%a} {d.day}</div>'
        if f:
            cell = (
                f'{top}<div style="font-size:24px;line-height:1.35">{weather_icon(f)}</div>'
                f'<div style="font-size:13px;font-weight:600;color:{INK}">{esc(f["low"])}–{esc(f["high"])}°C</div>'
                f'<div style="font-size:12px;line-height:1.35;color:{MUTED}">{esc(f["summary"])}</div>'
            )
        else:
            note = "Forecast not out yet" if d > today + timedelta(days=4) else "No forecast"
            cell = f'{top}<div style="margin-top:6px;font-size:12px;color:{MUTED}">{note}</div>'
        cells.append(f'<td valign="top" width="{100 // len(wk.days)}%" style="padding:0 4px">{cell}</td>')
    days = [fc["days"][d.isoformat()] for d in wk.days if d.isoformat() in fc["days"]]
    advice = ""
    if wet_afternoons(days):
        bg, fg = CHIP["soon"]
        advice = (
            f'<div style="margin-top:12px;padding:10px 12px;border-radius:10px;background:{bg};color:{fg};'
            f'font-size:14px;line-height:1.45">{esc(ADVICE)}</div>'
        )
    return card(table(f"<tr>{''.join(cells)}</tr>") + advice, padding="14px 12px")


# The message.

def compose(store: dict, settings: dict, fc: dict | None, today: date) -> Message:
    year = today.year
    events = plan.upcoming(store["events"], today, settings["home"])
    wk = plan.weekend(today, settings["public_holidays"])
    picks = plan.picks_for(events, wk, settings)
    also, not_toddler = plan.also_on(events, wk, picks)
    ahead = plan.book_ahead(events, today, settings)
    later = plan.later_weekends(events, wk, today, settings, picks)
    holiday = holiday_line(wk, settings["public_holidays"])
    forecast_days = [fc["days"][d.isoformat()] for d in wk.days if fc and d.isoformat() in fc["days"]]
    wet = wet_afternoons(forecast_days)

    subject = f"Weekend go where? {span(wk, year)}"
    preheader = (
        " · ".join(e["title"] for e in picks[:3]) + (" and more" if len(picks) > 3 else "")
        if picks else "Nothing for a toddler is listed for this weekend yet"
    ) + (". Showers most afternoons." if wet else ".")

    sources = sorted({SOURCE_NAMES.get(s["source_id"], s["source_id"]) for e in events for s in e["sources"]})
    suits = sum(1 for e in events if plan.fit(e) != "low")
    footer = []
    if store.get("updated"):
        updated = date.fromisoformat(store["updated"])
        listed = f"Made from the events listed by {joined(sources)}, last" if sources else "Events"
        footer.append(
            f"{listed} updated {updated:%a} {fmt(updated, year)}: "
            f"{len(events)} upcoming events, {suits} of them suitable for a toddler."
        )
    footer.append("Distances are in a straight line from home.")
    if fc and fc.get("issued"):
        footer.append(f"Forecast: NEA four-day outlook, issued {clock(datetime.fromisoformat(fc['issued']))}.")
    footer.append("Reply to this email to say what to change.")
    left_out = ""
    if not_toddler:
        left_out = (
            "Left out: 1 event that is not really a toddler outing" if not_toddler == 1
            else f"Left out: {not_toddler} events that are not really toddler outings"
        ) + f" {NOT_TODDLER}."
    more = len(also) - min(len(also), ALSO_MAX)

    # HTML
    rows = [
        f'<tr><td style="padding:4px 4px 14px">'
        f'<div style="font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{TEAL}">'
        f"Weekend go where?</div>"
        f'<div style="margin-top:4px;font-size:28px;font-weight:800;line-height:1.15;color:{INK}">{esc(span(wk, year))}</div>'
        + (f'<div style="margin-top:4px;font-size:15px;color:{MUTED}">{esc(holiday)}</div>' if holiday else "")
        + "</td></tr>",
        weather_html(wk, fc, today),
        heading("Our picks", "Chosen for a toddler. Events that end soon, are near home or are free come first."),
    ]
    if picks:
        rows += [pick_html(i + 1, e, wk, settings) for i, e in enumerate(picks)]
    else:
        rows.append(card(f'<div style="{META}">Nothing good for a toddler is listed for this weekend yet.</div>'))
    if also or left_out:
        rows.append(heading("Also this weekend", "Other events that suit a toddler, best matches first, then nearest."))
        items = [
            row_html(e, i == 0, [where_html(e), price_html(e), esc(days_text(e, wk))]
                     + ([f'<span style="color:{BAD};font-weight:600">Fully booked</span>'] if plan.fully_booked(e) else []))
            for i, e in enumerate(also[:ALSO_MAX])
        ]
        tail = " ".join(t for t in (f"And {more} more." if more else "", left_out) if t)
        if tail:
            border = f"border-top:1px solid {LINE};" if items else ""
            items.append(f'<tr><td style="{border}padding:10px 0;{META}">{esc(tail)}</td></tr>')
        rows.append(card(table("".join(items)), padding="6px 16px"))
    if ahead:
        rows.append(heading("Book ahead", "Sessions in the next six weeks that need booking."))
        items = []
        for i, e in enumerate(ahead):
            start, end = date.fromisoformat(e["dates"]["start"]), date.fromisoformat(e["dates"]["end"])
            when = f"{start:%a} {fmt(start, year)}" if start == end else f"{fmt(start, year)} to {fmt(end, year)}"
            items.append(row_html(e, i == 0, [esc(when), where_html(e), price_html(e)], lead=date_box(start)))
        rows.append(card(table("".join(items)), padding="6px 16px"))
    if any(top for _, top in later):
        rows.append(heading("The weekends after", "The top three for each."))
        for w, top in later:
            title = span(w, year) + (" · long weekend" if len(w.days) > 2 else "")
            items = [f'<tr><td style="padding:10px 0 2px;font-size:14px;font-weight:700;color:{TEAL}">{esc(title)}</td></tr>']
            if not top:
                items.append(f'<tr><td style="padding:6px 0 10px;{META}">Nothing listed yet.</td></tr>')
            items += [row_html(e, i == 0, [where_html(e), price_html(e)]) for i, e in enumerate(top)]
            rows.append(card(table("".join(items)), padding="6px 16px"))
    rows.append(
        f'<tr><td style="padding:14px 4px 0;font-size:13px;line-height:1.5;color:{MUTED}">'
        + "<br>".join(esc(line) for line in footer)
        + "</td></tr>"
    )
    page = (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '<meta name="color-scheme" content="light">\n'
        f"<title>{esc(subject)}</title>\n</head>\n"
        f'<body style="margin:0;padding:0;background:{BG}">\n'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{esc(preheader)}</div>\n'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{BG}">'
        f'<tr><td align="center" style="padding:20px 12px 32px">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="max-width:600px;font-family:{FONT};color:{INK}">\n'
        + "\n".join(r for r in rows if r)
        + "\n</table></td></tr></table>\n</body>\n</html>\n"
    )

    # Plain text
    lines = ["WEEKEND GO WHERE?", span(wk, year)] + ([holiday] if holiday else [])
    if forecast_days:
        lines += ["", "WEATHER"]
        for d in wk.days:
            f = fc["days"].get(d.isoformat())
            lines.append(f"{d:%a} {d.day}: " + (f"{f['summary']}, {f['low']}–{f['high']}°C" if f else "no forecast yet"))
        if wet:
            lines.append(ADVICE)
    lines += ["", "OUR PICKS"]
    if not picks:
        lines.append("Nothing good for a toddler is listed for this weekend yet.")
    for i, e in enumerate(picks, 1):
        ends = timing(e, wk, settings)
        tags = [plan.price_text(e)[0]] + ([ends[0]] if ends else []) + (["Book ahead"] if plan.needs_booking(e) else [])
        tags += [age_text(e)] if age_text(e) else []
        when = days_text(e, wk) + (f" · {e['dates']['times']}" if e["dates"].get("times") else "")
        where = [e["venue"]["name"]] + [t for t in (km_text(e), SETTING.get(e["setting"])) if t]
        lines += ["", f"{i}. {e['title']}", when, " · ".join(where), " · ".join(tags), e["summary"]]
        if price_detail(e):
            lines.append(f"Price: {price_detail(e)}")
        lines += [f"{text}: {url}" for text, url in links(e)]
    if also or left_out:
        lines += ["", "ALSO THIS WEEKEND"]
        for e in also[:ALSO_MAX]:
            bits = [e["venue"]["name"]] + ([km_text(e)] if km_text(e) else []) + [plan.price_text(e)[0], days_text(e, wk)]
            lines.append(f"- {e['title']}: " + " · ".join(bits) + (" · Fully booked" if plan.fully_booked(e) else ""))
            if main_link(e):
                lines.append(f"  {main_link(e)}")
        lines += [t for t in (f"And {more} more." if more else "", left_out) if t]
    if ahead:
        lines += ["", "BOOK AHEAD"]
        for e in ahead:
            start = date.fromisoformat(e["dates"]["start"])
            lines.append(f"- {start:%a} {fmt(start, year)}: {e['title']}, {e['venue']['name']}")
            lines.append(f"  {main_link(e)}")
    if any(top for _, top in later):
        lines += ["", "THE WEEKENDS AFTER"]
        for w, top in later:
            lines.append(span(w, year) + (" · long weekend" if len(w.days) > 2 else ""))
            lines += [f"- {e['title']}, {e['venue']['name']}" + (f" · {km_text(e)}" if km_text(e) else "") for e in top]
            if not top:
                lines.append("- Nothing listed yet.")
    lines += ["", *footer]
    return Message(subject, preheader, page, "\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the weekly email to dist/.")
    parser.add_argument("--date", type=date.fromisoformat, help="build as if sent on this day")
    args = parser.parse_args(argv)
    store = load_json(EVENTS_FILE, {"updated": None, "events": []})
    message = compose(store, plan.load_settings(), forecast(), args.date or sg_today())
    DIST.mkdir(exist_ok=True)
    (DIST / "email.html").write_text(message.html, encoding="utf-8")
    (DIST / "email.txt").write_text(message.text, encoding="utf-8")
    (DIST / "email-subject.txt").write_text(message.subject + "\n", encoding="utf-8")
    print(message.subject)
    for name in ("email.html", "email.txt", "email-subject.txt"):
        path = DIST / name
        print(f"Wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
