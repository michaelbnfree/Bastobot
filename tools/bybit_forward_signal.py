#!/usr/bin/env python3
"""Paper-only BTC volatility signal from the Bybit option snapshots."""

from __future__ import annotations

import gzip
import json
import math
import sqlite3
import sys
import time
from datetime import datetime
from datetime import datetime, timezone
from pathlib import Path


OPTION_FILE = Path("/root/bastobot/data/bybit_options/btc_option_chain.jsonl")
BTC_DB = Path("/root/barry-research-artifacts/short-mean-reversion-grid-backtest.db")
LIVE_BTC_DB = Path("/root/bastobot/data/bybit_options/live_btc_1m.db")
OUTPUT = Path("/root/bastobot/data/bybit_options/forward_vol_signals.jsonl")

# The collector writes every 5 minutes and this script runs in the same second, so it normally reads the
# previous tick (about 5 minutes old). Tolerate one missed collector run, refuse anything older: a dead
# or stalled collector must not produce signals from an old option chain.
MAX_SNAPSHOT_AGE_MS = 15 * 60 * 1000
MAX_CLOCK_SKEW_MS = 60 * 1000


class StaleSnapshotError(RuntimeError):
    """The newest option-chain snapshot is too old (or from the future) to trade on."""


def _last_line(path: Path) -> str | None:
    """Last non-empty line of a plain or .gz file; None when the file is missing or empty."""
    if not path.exists():
        return None
    if path.suffix == ".gz":
        last = None
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last = line
        return last
    size = path.stat().st_size
    if size == 0:
        return None
    block, data = 1 << 20, b""
    with path.open("rb") as handle:
        pos = size
        while pos > 0:
            step = min(block, pos)
            pos -= step
            handle.seek(pos)
            data = handle.read(step) + data
            lines = [ln for ln in data.split(b"\n") if ln.strip()]
            # a full line precedes the last one, or we have reached the start of the file
            if len(lines) >= 2 or pos == 0:
                return lines[-1].decode("utf-8") if lines else None
    return None


def load_latest_snapshot(option_file: Path | None = None, now_ms: int | None = None) -> dict:
    """Newest option-chain snapshot, from the live file or (right after a logrotate) the newest
    rotated sibling, rejected when older than MAX_SNAPSHOT_AGE_MS or timestamped in the future."""
    option_file = option_file or OPTION_FILE
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    candidates = [option_file] + sorted(
        option_file.parent.glob(option_file.name + "-*"), key=lambda p: p.name, reverse=True)
    line, source = None, None
    for candidate in candidates:
        line = _last_line(candidate)
        if line:
            source = candidate
            break
    if line is None:
        raise StaleSnapshotError(f"no option snapshot found in {option_file} or its rotated files")
    snapshot = json.loads(line)
    age_ms = now_ms - int(snapshot["captured_epoch_ms"])
    if age_ms > MAX_SNAPSHOT_AGE_MS:
        raise StaleSnapshotError(
            f"newest snapshot ({snapshot.get('captured_at')}, from {source.name}) is {age_ms / 60000:.1f} min old; "
            f"limit {MAX_SNAPSHOT_AGE_MS / 60000:.0f} min. Is the collector running?")
    if age_ms < -MAX_CLOCK_SKEW_MS:
        raise StaleSnapshotError(
            f"newest snapshot ({snapshot.get('captured_at')}) is {-age_ms / 1000:.0f}s in the future; check the clock")
    return snapshot


def rv_30d(captured_ms: int) -> tuple[float | None, str | None, bool]:
    if LIVE_BTC_DB.exists():
        with sqlite3.connect(LIVE_BTC_DB) as db:
            rows = db.execute("SELECT close FROM candles ORDER BY opened_at_ms DESC LIMIT 43201").fetchall()
            latest = db.execute("SELECT max(opened_at_ms) FROM candles").fetchone()
        latest_ms = int(latest[0]) if latest and latest[0] else 0
        latest_at = datetime.fromtimestamp(latest_ms / 1000, timezone.utc).isoformat() if latest_ms else None
        fresh = latest_ms >= captured_ms - 2 * 86_400_000
        if len(rows) >= 2881:
            closes = [float(row[0]) for row in reversed(rows)]
            returns = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
            if len(returns) >= 100:
                mean = sum(returns) / len(returns)
                variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
                return math.sqrt(variance * 365 * 24 * 60), latest_at, fresh
        return None, latest_at, False

    with sqlite3.connect(BTC_DB) as db:
        rows = db.execute(
            """
            SELECT close FROM historical_candles
            WHERE symbol = 'BINANCE_USDM:BTCUSDT' AND interval = '15m'
            ORDER BY closed_at DESC LIMIT 2881
            """
        ).fetchall()
        latest = db.execute(
            """SELECT closed_at FROM historical_candles
               WHERE symbol = 'BINANCE_USDM:BTCUSDT' AND interval = '15m'
               ORDER BY closed_at DESC LIMIT 1"""
        ).fetchone()
    latest_at = latest[0] if latest else None
    latest_ms = int(datetime.fromisoformat(latest_at.replace("Z", "+00:00")).timestamp() * 1000) if latest_at else 0
    fresh = latest_ms >= captured_ms - 2 * 86_400_000
    closes = [float(row[0]) for row in reversed(rows)]
    if len(closes) < 100:
        return None, latest_at, fresh
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    if len(returns) < 100:
        return None, latest_at, fresh
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance * 4 * 365 * 24), latest_at, fresh


def main(now_ms: int | None = None) -> None:
    latest = load_latest_snapshot(OPTION_FILE, now_ms)
    tickers = latest["tickers"]
    now = latest["captured_at"]
    underlying = [float(t["underlyingPrice"]) for t in tickers if t.get("underlyingPrice")]
    if not underlying:
        raise RuntimeError("No underlyingPrice in Bybit option snapshot")
    spot = sum(underlying) / len(underlying)
    captured_ms = latest["captured_epoch_ms"]

    candidates = []
    for t in tickers:
        if not t.get("symbol"):
            continue
        try:
            parts = t["symbol"].split("-")
            strike = float(parts[2])
            expiry = datetime.strptime(parts[1], "%d%b%y").replace(tzinfo=timezone.utc)
            expiry_ms = int(expiry.timestamp() * 1000)
            iv = float(t["markIv"])
            oi = float(t.get("openInterest") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        days = (expiry_ms - captured_ms) / 86_400_000
        if 20 <= days <= 45 and oi > 0 and iv > 0:
            candidates.append((abs(days - 30), abs(strike / spot - 1), expiry_ms, strike, t))
    if not candidates:
        raise RuntimeError("No usable 20-45 day option candidates")
    _, _, expiry_ms, strike, _ = min(candidates, key=lambda row: (row[0], row[1], row[2], row[3]))
    same = []
    for t in tickers:
        try:
            parts = t["symbol"].split("-")
            t_expiry = int(datetime.strptime(parts[1], "%d%b%y").replace(tzinfo=timezone.utc).timestamp() * 1000)
            t_strike = float(parts[2])
            if t_expiry == expiry_ms and abs(t_strike - strike) < 1e-9:
                same.append(t)
        except (KeyError, IndexError, ValueError):
            continue
    calls = [t for t in same if "-C-" in t["symbol"]]
    puts = [t for t in same if "-P-" in t["symbol"]]
    if not calls or not puts:
        raise RuntimeError("ATM call/put pair unavailable")
    call, put = calls[0], puts[0]
    iv = (float(call["markIv"]) + float(put["markIv"])) / 2
    rv, rv_source_latest, rv_fresh = rv_30d(captured_ms)
    spread = iv - rv if rv is not None else None
    action = "HOLD" if not rv_fresh or spread is None or abs(spread) < 0.05 else ("SELL_VOL" if spread > 0 else "BUY_VOL")
    record = {
        "captured_at": now,
        "spot_underlying": spot,
        "expiry_ms": expiry_ms,
        "days_to_expiry": (expiry_ms - captured_ms) / 86_400_000,
        "strike": strike,
        "call_symbol": call["symbol"],
        "put_symbol": put["symbol"],
        "call_mark_iv": float(call["markIv"]),
        "put_mark_iv": float(put["markIv"]),
        "atm_straddle_iv": iv,
        "realized_vol_30d": rv,
        "realized_vol_source_latest": rv_source_latest,
        "realized_vol_fresh": rv_fresh,
        "iv_minus_rv": spread,
        "signal": action,
        "paper_only": True,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    print(json.dumps(record, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except StaleSnapshotError as exc:
        print(f"STALE-DATA: no signal written: {exc}", file=sys.stderr)
        sys.exit(2)
