"""
Per-trade monitor — track entry, SL, TP1, TP2 for any horizon.
Separate from market snapshots: enter a trade, scanner checks price every 5 min.
Alerts on TP1/TP2/SL hits. Logs to Notion Trade Monitor DB.
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

_LIST_KEY  = "trade_monitor:list"
_TRADE_KEY = "trade_monitor:{tid}"
_NOTIF_KEY = "trade_monitor:notified:{tid}:{event}"

NOTION_API_KEY      = os.getenv("NOTION_API_KEY")
NOTION_VERSION      = "2022-06-28"
TRADE_MONITOR_DB_ID = os.getenv("NOTION_TRADE_MONITOR_DB_ID", "")

_TG_TOKEN = "***REDACTED_TELEGRAM_TOKEN***"
_TG_CHAT  = 298886049

_HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type":  "application/json",
    "Notion-Version": NOTION_VERSION,
}


def _send_tg(text: str) -> None:
    try:
        requests.post(
            f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
            json={"chat_id": _TG_CHAT, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        print(f"[TRADE MON] TG failed: {e}")


def _log_to_notion(trade: dict) -> tuple[str | None, str | None]:
    """Returns (page_url, page_id) or (None, None) on failure."""
    if not NOTION_API_KEY or not TRADE_MONITOR_DB_ID:
        return None, None
    now   = datetime.now(timezone.utc)
    title = f"{trade['symbol']} {trade['direction']} — {now.strftime('%b %d, %Y')}"
    props = {
        "Title":     {"title": [{"text": {"content": title}}]},
        "Asset":     {"select": {"name": trade["symbol"]}},
        "Direction": {"select": {"name": trade["direction"]}},
        "Horizon":   {"select": {"name": trade["horizon"].capitalize()}},
        "Entry":     {"number": trade["entry"]},
        "SL":        {"number": trade["sl"]},
        "TP1":       {"number": trade["tp1"]},
        "Status":    {"select": {"name": "Open"}},
        "Date":      {"date": {"start": now.isoformat()}},
    }
    if trade.get("tp2"):
        props["TP2"] = {"number": trade["tp2"]}
    if trade.get("conviction"):
        props["Conviction"] = {"select": {"name": trade["conviction"]}}
    if trade.get("session"):
        props["Session"] = {"select": {"name": trade["session"]}}
    if trade.get("notes"):
        props["Notes"] = {"rich_text": [{"text": {"content": trade["notes"][:2000]}}]}
    try:
        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers=_HEADERS,
            json={"parent": {"database_id": TRADE_MONITOR_DB_ID}, "properties": props},
            timeout=10,
        )
        r.raise_for_status()
        page  = r.json()
        url   = page.get("url", "")
        # Notion page ID is the last path segment without hyphens
        pid   = page.get("id", "").replace("-", "")
        return url, pid
    except Exception as e:
        print(f"[TRADE MON] Notion log failed: {e}")
    return None, None


def _update_notion_status(page_id: str, status: str, pnl_pct: float | None = None) -> None:
    if not NOTION_API_KEY or not page_id:
        return
    props: dict = {"Status": {"select": {"name": status}}}
    if pnl_pct is not None:
        props["Outcome %"] = {"number": round(pnl_pct, 2)}
    try:
        requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=_HEADERS,
            json={"properties": props},
            timeout=10,
        )
    except Exception:
        pass


def enter_trade(
    symbol:     str,
    direction:  str,          # "Long" or "Short"
    entry:      float,
    sl:         float,
    tp1:        float,
    tp2:        float | None = None,
    horizon:    str = "swing",
    conviction: str | None = None,
    session:    str | None = None,
    notes:      str = "",
) -> dict:
    tid = str(uuid.uuid4())[:8]
    trade = {
        "id":         tid,
        "symbol":     symbol.upper(),
        "direction":  direction.capitalize(),
        "entry":      entry,
        "sl":         sl,
        "tp1":        tp1,
        "tp2":        tp2,
        "horizon":    horizon,
        "conviction": conviction,
        "session":    session,
        "notes":      notes,
        "status":     "Open",
        "entered_at": datetime.now(timezone.utc).isoformat(),
        "notion_url": None,
        "notion_id":  None,
    }
    notion_url, notion_id = _log_to_notion(trade)
    trade["notion_url"] = notion_url
    trade["notion_id"]  = notion_id

    _r.set(_TRADE_KEY.format(tid=tid), json.dumps(trade))
    ids = json.loads(_r.get(_LIST_KEY) or "[]")
    ids.append(tid)
    _r.set(_LIST_KEY, json.dumps(ids))

    return trade


def get_all_trades(status: str | None = None) -> list[dict]:
    ids    = json.loads(_r.get(_LIST_KEY) or "[]")
    trades = []
    for tid in ids:
        raw = _r.get(_TRADE_KEY.format(tid=tid))
        if not raw:
            continue
        t = json.loads(raw)
        if status is None or t.get("status") == status:
            trades.append(t)
    return trades


def get_all_open() -> list[dict]:
    return get_all_trades("Open")


def get_open_trade(symbol: str) -> dict | None:
    """Return the first open trade for this symbol, or None."""
    for t in get_all_open():
        if t["symbol"] == symbol.upper():
            return t
    return None


def check_trades(price_map: dict[str, float]) -> None:
    """Called by scanner loop. Checks every open trade against current prices."""
    for trade in get_all_open():
        sym   = trade["symbol"]
        price = price_map.get(sym)
        if price is None:
            continue

        is_long = trade["direction"] == "Long"
        tid     = trade["id"]

        sl_hit  = (is_long and price <= trade["sl"]) or (not is_long and price >= trade["sl"])
        tp1_hit = (is_long and price >= trade["tp1"]) or (not is_long and price <= trade["tp1"])
        tp2_hit = bool(trade.get("tp2")) and (
            (is_long and price >= trade["tp2"]) or (not is_long and price <= trade["tp2"])
        )

        def pnl(p):
            return (p - trade["entry"]) / trade["entry"] * 100 if is_long else (trade["entry"] - p) / trade["entry"] * 100

        notif_sl  = _NOTIF_KEY.format(tid=tid, event="sl")
        notif_tp1 = _NOTIF_KEY.format(tid=tid, event="tp1")
        notif_tp2 = _NOTIF_KEY.format(tid=tid, event="tp2")

        if sl_hit and not _r.get(notif_sl):
            _r.set(notif_sl, "1")
            pct = pnl(price)
            _send_tg(
                f"🛑 *{sym} SL Hit* — {trade['direction']} {trade['horizon']}\n"
                f"SL: ${trade['sl']:,.2f}  |  Entry: ${trade['entry']:,.2f}\n"
                f"P&L: {pct:.1f}%"
            )
            _update_trade_status(tid, "SL Hit", pct)

        elif tp1_hit and not _r.get(notif_tp1):
            _r.set(notif_tp1, "1")
            pct = pnl(price)
            _send_tg(
                f"✅ *{sym} TP1 Hit* — {trade['direction']} {trade['horizon']}\n"
                f"TP1: ${trade['tp1']:,.2f}  |  Entry: ${trade['entry']:,.2f}\n"
                f"P&L: {pct:.1f}%"
                + (" — move SL to break-even" if trade.get("tp2") else "")
            )
            if not trade.get("tp2"):
                _update_trade_status(tid, "TP1 Hit", pct)

        if tp2_hit and not _r.get(notif_tp2):
            _r.set(notif_tp2, "1")
            pct = pnl(price)
            _send_tg(
                f"🎯 *{sym} TP2 Hit* — {trade['direction']} {trade['horizon']}\n"
                f"TP2: ${trade['tp2']:,.2f}  |  Entry: ${trade['entry']:,.2f}\n"
                f"P&L: {pct:.1f}% — full target reached"
            )
            _update_trade_status(tid, "TP2 Hit", pct)


def _update_trade_status(tid: str, status: str, pnl_pct: float | None = None) -> None:
    raw = _r.get(_TRADE_KEY.format(tid=tid))
    if not raw:
        return
    trade = json.loads(raw)
    trade["status"]    = status
    trade["closed_at"] = datetime.now(timezone.utc).isoformat()
    if pnl_pct is not None:
        trade["pnl_pct"] = round(pnl_pct, 2)
    _r.set(_TRADE_KEY.format(tid=tid), json.dumps(trade))
    if trade.get("notion_id"):
        _update_notion_status(trade["notion_id"], status, pnl_pct)


def close_trade(symbol: str, status: str = "Closed") -> tuple[bool, str]:
    for trade in get_all_open():
        if trade["symbol"] == symbol.upper():
            _update_trade_status(trade["id"], status)
            return True, f"Closed {symbol} {trade['direction']} {trade['horizon']} trade."
    return False, f"No open {symbol} trade found."


def format_open_trades() -> str:
    trades = get_all_open()
    if not trades:
        return "No open trades.\n\nEnter one: `trade <COIN> long/short <entry> sl <sl> tp1 <tp1> [tp2 <tp2>] [scalp/day/swing/position]`"
    lines = [f"📊 *Open Trades ({len(trades)}):*\n"]
    for i, t in enumerate(trades, 1):
        tp2_str  = f"  TP2: ${t['tp2']:,.2f}" if t.get("tp2") else ""
        conv_str = f"  Conviction: {t['conviction']}" if t.get("conviction") else ""
        notion   = f"\n  [📓 View in Notion]({t['notion_url']})" if t.get("notion_url") else ""
        # Quick live context: how far from entry/TP/SL
        lines.append(
            f"{i}. *{t['symbol']} {t['direction']}* — {t['horizon'].capitalize()}{conv_str}\n"
            f"  Entry: ${t['entry']:,.2f}  SL: ${t['sl']:,.2f}\n"
            f"  TP1: ${t['tp1']:,.2f}{tp2_str}"
            f"{notion}"
        )
    return "\n".join(lines)
