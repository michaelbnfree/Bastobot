"""
Hot Top Trades — high-conviction setups surfaced by the scanner.
Populated automatically when conviction score ≥ threshold.
Queryable via Barry: "hot trades" or "top setups".
"""

import os
import json
import uuid
import requests
import redis as _redis_lib
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv("/root/bastobot/.env")

_r = _redis_lib.Redis(host="localhost", port=6379, db=0)

_LIST_KEY     = "hot_trades:list"
_TRADE_KEY    = "hot_trades:{hid}"
_HOT_TTL      = 86400 * 3   # 3 days — auto-expires stale setups

NOTION_API_KEY   = os.getenv("NOTION_API_KEY")
NOTION_VERSION   = "2022-06-28"
HOT_TRADES_DB_ID = os.getenv("NOTION_HOT_TRADES_DB_ID", "")

HOT_THRESHOLD = 6.5  # conviction score to qualify

_HEADERS = {
    "Authorization":  f"Bearer {NOTION_API_KEY}",
    "Content-Type":   "application/json",
    "Notion-Version": NOTION_VERSION,
}


def _log_to_notion(entry: dict) -> str | None:
    if not NOTION_API_KEY or not HOT_TRADES_DB_ID:
        return None
    now   = datetime.now(timezone.utc)
    title = (
        f"🔥 {entry['symbol']} {entry['direction']} — "
        f"{entry['label']} ({now.strftime('%b %d %H:%M')})"
    )
    props = {
        "Title":     {"title": [{"text": {"content": title}}]},
        "Asset":     {"select": {"name": entry["symbol"]}},
        "Direction": {"select": {"name": entry["direction"]}},
        "Horizon":   {"select": {"name": entry["horizon"].capitalize()}},
        "Score":     {"number": entry["score"]},
        "Conviction":{"select": {"name": entry["label"]}},
        "Date":      {"date": {"start": now.isoformat()}},
        "Status":    {"select": {"name": "Active"}},
        "Signals":   {"rich_text": [{"text": {"content": "\n".join(entry["signals"][:10])}}]},
    }
    try:
        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers=_HEADERS,
            json={"parent": {"database_id": HOT_TRADES_DB_ID}, "properties": props},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("url")
    except Exception as e:
        print(f"[HOT TRADES] Notion log failed: {e}")
    return None


def _get_by_symbol(symbol: str) -> dict | None:
    ids = json.loads(_r.get(_LIST_KEY) or "[]")
    for hid in ids:
        raw = _r.get(_TRADE_KEY.format(hid=hid))
        if raw:
            t = json.loads(raw)
            if t.get("symbol") == symbol:
                return t
    return None


def add_or_update(symbol: str, conviction: dict) -> bool:
    """
    Add or refresh a hot trade. Returns True if this is a new entry.
    No-op if existing entry has equal or higher score.
    """
    if conviction["score"] < HOT_THRESHOLD:
        return False

    existing = _get_by_symbol(symbol)
    if existing and existing.get("score", 0) >= conviction["score"]:
        return False

    hid   = existing["id"] if existing else str(uuid.uuid4())[:8]
    entry = {
        "id":        hid,
        "symbol":    symbol,
        "score":     conviction["score"],
        "label":     conviction["label"],
        "direction": conviction["direction"].capitalize(),
        "horizon":   conviction["horizon"],
        "signals":   conviction["signals"],
        "updated":   datetime.now(timezone.utc).isoformat(),
        "notion_url":existing.get("notion_url") if existing else None,
    }

    if not existing:
        entry["notion_url"] = _log_to_notion(entry)

    _r.setex(_TRADE_KEY.format(hid=hid), _HOT_TTL, json.dumps(entry))

    ids = json.loads(_r.get(_LIST_KEY) or "[]")
    if hid not in ids:
        ids.append(hid)
        _r.set(_LIST_KEY, json.dumps(ids))

    return not bool(existing)


def get_all() -> list[dict]:
    ids    = json.loads(_r.get(_LIST_KEY) or "[]")
    trades = []
    for hid in ids:
        raw = _r.get(_TRADE_KEY.format(hid=hid))
        if raw:
            trades.append(json.loads(raw))
    return sorted(trades, key=lambda x: x.get("score", 0), reverse=True)


def format_hot_trades() -> str:
    trades = get_all()
    if not trades:
        return (
            "🔍 No high-conviction setups right now.\n"
            "Scanner runs every 5 min — check back soon.\n\n"
            "Or trigger a manual scan: `scan`"
        )
    lines = [f"🔥 *Hot Top Trades* ({len(trades)} active)\n"]
    for i, t in enumerate(trades, 1):
        age_str = ""
        try:
            updated = datetime.fromisoformat(t["updated"])
            mins    = int((datetime.now(timezone.utc) - updated).total_seconds() / 60)
            age_str = f" · {mins}min ago"
        except Exception:
            pass
        notion_link = f" [📓]({t['notion_url']})" if t.get("notion_url") else ""
        lines.append(
            f"{i}. *{t['symbol']}* — {t['direction']} | "
            f"{t['label']} ({t['score']}/10) | "
            f"{t['horizon'].capitalize()}{age_str}{notion_link}"
        )
        for sig in t["signals"][:3]:
            lines.append(f"  • {sig}")
        lines.append("")
    lines.append("_To monitor a setup: `trade <COIN> long/short <entry> sl <sl> tp1 <tp1>`_")
    return "\n".join(lines)
