"""Build the household web page from data/ into dist/.

Usage:
    python site/build.py

Writes two files:
    dist/index.html     a full page, for a static host such as Cloudflare Pages
    dist/artifact.html  the same page without the document wrapper, for a claude.ai artifact

Everything the page shows is embedded in it, so it needs no server and makes no requests:
the events, the household settings, a Singapore outline for the map (site/singapore.json),
and NEA's four-day forecast as it stood when the page was built (left out if NEA cannot be
reached).
"""
from __future__ import annotations

import json
import math
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from refresh.common import CONFIG_DIR, EVENTS_FILE, load_json, load_yaml, sg_now  # noqa: E402

TEMPLATE = ROOT / "site" / "template.html"
OUTLINE = ROOT / "site" / "singapore.json"
DIST = ROOT / "dist"
MARKER = "<!--BODY-->"
PLACEHOLDER = "/*__DATA__*/null"
FORECAST_URL = "https://api-open.data.gov.sg/v2/real-time/api/four-day-outlook"
MAP_WIDTH = 1000  # SVG user units; the page scales it to fit


def singapore_map() -> dict:
    """Project the outline to SVG coordinates. Equirectangular is exact enough at this size."""
    outline = load_json(OUTLINE)
    rings = outline["rings"]
    lons = [p[0] for r in rings for p in r]
    lats = [p[1] for r in rings for p in r]
    lon0, lat0 = min(lons), max(lats)
    kx = MAP_WIDTH / (max(lons) - lon0)
    ky = kx / math.cos(math.radians((min(lats) + lat0) / 2))
    height = round((lat0 - min(lats)) * ky)
    path = " ".join(
        "M" + " L".join(f"{(lon - lon0) * kx:.1f},{(lat0 - lat) * ky:.1f}" for lon, lat in ring) + " Z"
        for ring in rings
    )
    return {"path": path, "width": MAP_WIDTH, "height": height, "lon0": lon0, "lat0": lat0, "kx": kx, "ky": ky,
            "credit": "Map outline: geoBoundaries, from URA data (ODbL)"}


def forecast() -> dict | None:
    """NEA's four-day outlook by date, or None when it cannot be fetched."""
    req = urllib.request.Request(FORECAST_URL, headers={"User-Agent": "weekend-go-where/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            record = json.load(resp)["data"]["records"][0]
    except Exception as exc:  # the page works without it
        print(f"Forecast left out: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    days = {
        f["timestamp"][:10]: {
            "summary": f["forecast"]["summary"],
            "text": f["forecast"]["text"],
            "low": f["temperature"]["low"],
            "high": f["temperature"]["high"],
        }
        for f in record["forecasts"]
    }
    return {"issued": record.get("updatedTimestamp") or record.get("timestamp"), "days": days}


def page_data() -> dict:
    settings = load_yaml(CONFIG_DIR / "settings.yaml")
    planning, home = settings.get("planning", {}), settings.get("home", {})
    store = load_json(EVENTS_FILE, {"updated": None, "events": []})
    return {
        "updated": store["updated"],
        "built": sg_now().isoformat(timespec="minutes"),
        "events": store["events"],
        "settings": {
            "limited_max_days": int(planning.get("limited_max_days", 42)),
            "last_chance_days": int(planning.get("last_chance_days", 14)),
            # YAML reads the date keys as dates; the page wants ISO strings.
            "public_holidays": {str(k): str(v) for k, v in (planning.get("public_holidays") or {}).items()},
            "home": {"label": home.get("label", "Home"), "lat": home.get("lat"), "lng": home.get("lng")},
        },
        "map": singapore_map(),
        "forecast": forecast(),
    }


def build() -> tuple[Path, Path]:
    template = TEMPLATE.read_text(encoding="utf-8")
    if MARKER not in template or PLACEHOLDER not in template:
        raise SystemExit(f"{TEMPLATE} is missing {MARKER!r} or {PLACEHOLDER!r}")
    # "</" inside a script would end it early, so escape it in the embedded JSON.
    data = json.dumps(page_data(), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = template.replace(PLACEHOLDER, data)
    head, body = page.split(MARKER, 1)
    full = (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
        '<meta name="robots" content="noindex">\n'
        f"{head}</head>\n<body>{body}</body>\n</html>\n"
    )
    DIST.mkdir(exist_ok=True)
    index, artifact = DIST / "index.html", DIST / "artifact.html"
    index.write_text(full, encoding="utf-8")
    artifact.write_text(page.replace(MARKER, ""), encoding="utf-8")
    return index, artifact


if __name__ == "__main__":
    for path in build():
        print(f"Wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")
