"""Build the household web page from data/ into dist/.

Usage:
    python site/build.py

Writes two files:
    dist/index.html     a full page, for a static host such as Cloudflare Pages
    dist/artifact.html  the same page without the document wrapper, for a claude.ai artifact

The events and settings are embedded in the page, so it needs no server and no fetch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from refresh.common import CONFIG_DIR, EVENTS_FILE, load_json, load_yaml  # noqa: E402

TEMPLATE = ROOT / "site" / "template.html"
DIST = ROOT / "dist"
MARKER = "<!--BODY-->"
PLACEHOLDER = "/*__DATA__*/null"


def page_data() -> dict:
    planning = load_yaml(CONFIG_DIR / "settings.yaml").get("planning", {})
    store = load_json(EVENTS_FILE, {"updated": None, "events": []})
    return {
        "updated": store["updated"],
        "events": store["events"],
        "settings": {
            "limited_max_days": int(planning.get("limited_max_days", 42)),
            "last_chance_days": int(planning.get("last_chance_days", 14)),
            # YAML reads the date keys as dates; the page wants ISO strings.
            "public_holidays": {str(k): str(v) for k, v in (planning.get("public_holidays") or {}).items()},
        },
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
