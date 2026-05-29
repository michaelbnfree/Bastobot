"""
Logs Barry's trade ideas to the Notion Barry Trade Log database.
Called automatically after chart analysis when a directional setup is detected.
"""

import os
import re
import requests
from datetime import datetime, timezone

NOTION_API_KEY  = os.getenv("NOTION_API_KEY")
NOTION_VERSION  = "2022-06-28"
DATABASE_ID     = "a6f67bb95ed2474ebc14de0ed99a983f"

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}


def _extract_direction(text: str) -> str | None:
    t = text.lower()
    long_score  = sum([t.count(w) for w in ["long", "bullish", "buy", "upside", "bull"]])
    short_score = sum([t.count(w) for w in ["short", "bearish", "sell", "downside", "bear"]])
    if long_score == 0 and short_score == 0:
        return None
    return "Long" if long_score >= short_score else "Short"


def _extract_price(text: str, keywords: list[str]) -> float | None:
    for kw in keywords:
        pattern = rf"{kw}[:\s]*\$?([\d,]+(?:\.\d+)?)"
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


def log_trade_idea(analysis: str, asset: str = "BTC") -> str | None:
    """
    Parse Barry's analysis, create a Notion row. Returns the page URL or None on failure.
    Only logs if a clear directional bias is found.
    """
    if not NOTION_API_KEY:
        return None

    direction  = _extract_direction(analysis)
    if not direction:
        return None  # no trade idea detected

    entry_price = _extract_price(analysis, ["entry", "entry zone", "enter"])
    today       = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    trade_name  = f"{asset} {direction} — {datetime.now(timezone.utc).strftime('%b %d, %Y')}"

    properties = {
        "Trade":     {"title": [{"text": {"content": trade_name}}]},
        "Date":      {"date": {"start": today}},
        "Asset":     {"select": {"name": asset}},
        "Direction": {"select": {"name": direction}},
        "Status":    {"select": {"name": "Open"}},
        "Barry Thesis": {"rich_text": [{"text": {"content": analysis[:2000]}}]},
    }
    if entry_price:
        properties["Entry Price"] = {"number": entry_price}

    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": properties,
    }

    try:
        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers=HEADERS,
            json=payload,
            timeout=10,
        )
        r.raise_for_status()
        url = r.json().get("url", "")
        print(f"[NOTION] Trade logged: {trade_name} → {url}")
        return url
    except Exception as e:
        print(f"[NOTION] Log failed: {e}")
        return None
