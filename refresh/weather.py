"""NEA's four-day outlook, for the web page and the weekly email."""
from __future__ import annotations

import json
import sys
import urllib.request

FORECAST_URL = "https://api-open.data.gov.sg/v2/real-time/api/four-day-outlook"


def forecast() -> dict | None:
    """NEA's four-day outlook by date, or None when it cannot be fetched."""
    req = urllib.request.Request(FORECAST_URL, headers={"User-Agent": "weekend-go-where/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            record = json.load(resp)["data"]["records"][0]
    except Exception as exc:  # the page and the email work without it
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


def wet_afternoons(days: list[dict]) -> bool:
    """True when showers are forecast for at least half the afternoons among these days."""
    wet = [f for f in days if "afternoon" in f["summary"].lower()
           and any(w in (f["summary"] + f["text"]).lower() for w in ("thunder", "shower", "rain"))]
    return bool(days) and len(wet) >= -(-len(days) // 2)
