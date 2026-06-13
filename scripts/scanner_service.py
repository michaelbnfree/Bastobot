"""
BastoBot scanner service — main loop.

Every 5 minutes:
  1. Fetch + cache market data for all watched assets
  2. Evaluate conviction scores + fire alerts
  3. Update Hot Top Trades list
  4. Check open trades against live prices

Session open / candle close triggers (threaded so main loop isn't blocked):
  Session opens: Asia 00:00, London 07:00, NY 13:00 UTC
  4h candle closes: 00, 04, 08, 12, 16, 20 UTC (daily close = 00:00 fires as Asia + session snapshot)
"""

import sys
import time
import threading
import redis
from datetime import datetime, timezone, date

sys.path.insert(0, "/root/bastobot")

from dotenv import load_dotenv
load_dotenv("/root/bastobot/.env")

_r = redis.Redis(host="localhost", port=6379, db=0)

SCAN_INTERVAL = 300  # 5 minutes

SESSIONS = {
    "asia":   (0,  0),
    "london": (7,  0),
    "ny":     (13, 0),
}

_SESSION_HORIZONS = {
    "asia":   "swing",
    "london": "swing",
    "ny":     "day",
}


# ── Session / candle state helpers ────────────────────────────────────────────

def _session_fired_today(session: str) -> bool:
    return bool(_r.get(f"scanner:session_fired:{session}:{date.today().isoformat()}"))

def _mark_session_fired(session: str) -> None:
    _r.setex(f"scanner:session_fired:{session}:{date.today().isoformat()}", 86400, "1")

def _candle_fired(label: str, dt: datetime) -> bool:
    return bool(_r.get(f"scanner:candle_fired:{label}:{dt.date().isoformat()}:{dt.hour:02d}"))

def _mark_candle_fired(label: str, dt: datetime) -> None:
    _r.setex(f"scanner:candle_fired:{label}:{dt.date().isoformat()}:{dt.hour:02d}", 86400, "1")


# ── Session snapshot (threaded) ───────────────────────────────────────────────

def _run_session_snapshot(session: str, now: datetime) -> None:
    from skills.watchlist import get_all_symbols
    from skills.snapshot_logger import run_verified_snapshot

    horizon = _SESSION_HORIZONS.get(session, "swing")
    tag     = f"session-{session}"
    symbols = get_all_symbols()

    # BTC first as the market anchor
    if "BTC" in symbols:
        symbols = ["BTC"] + [s for s in symbols if s != "BTC"]

    print(f"[SESSION] {session.upper()} open — running snapshots for {symbols[:4]}")
    for symbol in symbols[:4]:  # cap to avoid API rate limits
        try:
            text, flags = run_verified_snapshot(tag=tag, asset=symbol, horizon=horizon)
            print(f"[SESSION] {symbol} done ({len(flags)} flags)")
            time.sleep(5)
        except Exception as e:
            print(f"[SESSION] {symbol} failed: {e}")


def _run_candle_snapshot(candle: str, now: datetime) -> None:
    """At 4h candle close: rescan all, update conviction + hot trades."""
    from skills.watchlist import get_all_symbols
    from skills.scanner import fetch_and_cache, check_alerts
    from skills.conviction import score as conv_score
    from skills.hot_trades import add_or_update

    print(f"[CANDLE] {candle} close at {now.hour:02d}:00 UTC — rescanning")
    for symbol in get_all_symbols():
        try:
            data = fetch_and_cache(symbol)
            if not data:
                continue
            check_alerts(symbol, data)
            cv = conv_score(data, symbol)
            if cv["score"] >= 6.5:
                is_new = add_or_update(symbol, cv)
                if is_new:
                    print(f"[HOT TRADE] New entry: {symbol} {cv['score']}/10 {cv['direction']}")
        except Exception as e:
            print(f"[CANDLE] {symbol} error: {e}")


# ── Trigger check (called each scan cycle) ────────────────────────────────────

def check_triggers(now: datetime) -> None:
    for session, (hour, minute) in SESSIONS.items():
        if now.hour == hour and now.minute < 5 and not _session_fired_today(session):
            _mark_session_fired(session)
            threading.Thread(
                target=_run_session_snapshot, args=(session, now), daemon=True
            ).start()

    # 4h closes (0, 4, 8, 12, 16, 20) — daily close at 0:00 is covered by asia session
    if now.hour % 4 == 0 and now.minute < 5 and not _candle_fired("4h", now):
        _mark_candle_fired("4h", now)
        if now.hour != 0:  # 00:00 already handled by asia session snapshot
            threading.Thread(
                target=_run_candle_snapshot, args=("4h", now), daemon=True
            ).start()


# ── Main scan ─────────────────────────────────────────────────────────────────

def run_scan() -> None:
    from skills.scanner import scan_all
    from skills.conviction import score as conv_score
    from skills.hot_trades import add_or_update
    from skills.trade_monitor import get_all_open, check_trades

    now = datetime.now(timezone.utc)
    print(f"[SCANNER] Scan — {now.strftime('%H:%M UTC')}")

    results = scan_all()

    for symbol, data in results.items():
        try:
            cv = conv_score(data, symbol)
            if cv["score"] >= 6.5:
                add_or_update(symbol, cv)
        except Exception as e:
            print(f"[SCANNER] conviction({symbol}): {e}")

    price_map = {
        sym: data.get("binance", {}).get("price")
        for sym, data in results.items()
        if data.get("binance", {}).get("price")
    }
    if price_map:
        check_trades(price_map)

    # Update auto watchlist slots with top 3 scored assets (excluding BTC)
    try:
        from skills.watchlist import set_auto
        from skills.conviction import score as conv_score
        scored = []
        for symbol, data in results.items():
            if symbol == "BTC":
                continue
            cv = conv_score(data, symbol)
            scored.append({
                "symbol":    symbol,
                "score":     cv["score"],
                "direction": cv["direction"],
                "updated":   now.isoformat(),
            })
        scored.sort(key=lambda x: x["score"], reverse=True)
        set_auto(scored[:3])
    except Exception as e:
        print(f"[SCANNER] auto watchlist update failed: {e}")

    print(f"[SCANNER] Done — {len(results)} assets")
    _r.set("scanner:last_scan", datetime.now(timezone.utc).isoformat())


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    print("[SCANNER] BastoBot scanner service starting...")
    while True:
        try:
            check_triggers(datetime.now(timezone.utc))
            run_scan()
        except Exception as e:
            print(f"[SCANNER] Loop error: {e}")
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
