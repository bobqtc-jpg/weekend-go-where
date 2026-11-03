"""Shared paths, config loading and small helpers for the refresh pipeline."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
SCHEMA_DIR = ROOT / "schema"
INBOX_DIR = ROOT / "inbox"
ARTICLES_DIR = INBOX_DIR / "articles"
EXTRACTED_DIR = INBOX_DIR / "extracted"
MANIFEST_FILE = INBOX_DIR / "manifest.json"

EVENTS_FILE = DATA_DIR / "events.json"
PLACES_FILE = DATA_DIR / "places.json"
SEEN_FILE = DATA_DIR / "seen.json"

# Singapore has no daylight saving time, so a fixed offset is exact.
SGT = timezone(timedelta(hours=8), name="SGT")


def sg_now() -> datetime:
    return datetime.now(SGT)


def sg_today() -> date:
    return sg_now().date()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: Any) -> None:
    """Write JSON atomically so a crash never leaves a half-written data file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp.replace(path)


def normalize(text: str | None) -> str:
    """Lowercase ASCII words only, for fuzzy matching and stable ids."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def stable_id(prefix: str, *parts: str | None) -> str:
    key = "|".join(normalize(p) for p in parts)
    return f"{prefix}_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def slugify(text: str, max_len: int = 60) -> str:
    slug = normalize(text).replace(" ", "-")[:max_len].strip("-")
    return slug or "untitled"
