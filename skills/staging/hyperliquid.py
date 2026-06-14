"""
Hyperliquid skill — market data + authenticated trading via agent wallet.

Auth is lazy-loaded from env on first trade call; read-only functions
(get_btc_perp, get_funding_history, get_candles, get_all_mids) need no credentials.

Promotion path: skills/staging/ → skills/active/ when validated in paper/live.
"""
import os
import time
import requests
from dotenv import load_dotenv
from functools import lru_cache

_BASE = "https://api.hyperliquid.xyz/info"
_TIMEOUT = 10

load_dotenv("/root/bastobot/.env")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _post(payload: dict) -> dict | list:
    r = requests.post(_BASE, json=payload, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


@lru_cache(maxsize=1)
def _exchange():
    """Lazy-init authenticated Exchange. Cached after first call."""
    from hyperliquid.exchange import Exchange
    from eth_account import Account

    key = os.getenv("HL_AGENT_PRIVATE_KEY")
    main = os.getenv("HL_MAIN_ADDRESS")
    if not key or not main:
        raise RuntimeError("HL_AGENT_PRIVATE_KEY and HL_MAIN_ADDRESS must be set in .env")
    acct = Account.from_key(key)
    return Exchange(acct, "https://api.hyperliquid.xyz", account_address=main)


@lru_cache(maxsize=1)
def _info():
    from hyperliquid.info import Info
    return Info("https://api.hyperliquid.xyz", skip_ws=True)


def _main_addr() -> str:
    return os.getenv("HL_MAIN_ADDRESS", "")


def _sz_from_usd(coin: str, sz_usd: float) -> float:
    """Convert a USD notional to coin quantity using current mid price."""
    mids = get_all_mids()
    px = mids.get(coin)
    if not px:
        raise ValueError(f"No mid price found for {coin}")
    return round(sz_usd / px, 6)


# ---------------------------------------------------------------------------
# Read-only market data (no auth required)
# ---------------------------------------------------------------------------

def get_btc_perp() -> dict:
    """
    Current BTC perp snapshot.

    Keys: mark_price, oracle_price, mid_price, premium_pct,
          funding_rate_pct (per 8h), funding_rate_annual_pct,
          oi_btc, oi_usd_bn, change_24h_pct,
          volume_24h_usd_bn, volume_24h_btc
    """
    data = _post({"type": "metaAndAssetCtxs"})
    universe = data[0]["universe"]
    ctxs = data[1]

    btc_idx = next(i for i, u in enumerate(universe) if u["name"] == "BTC")
    ctx = ctxs[btc_idx]

    mark        = float(ctx["markPx"])
    oracle      = float(ctx["oraclePx"])
    mid         = float(ctx["midPx"])
    funding     = float(ctx["funding"])
    oi_btc      = float(ctx["openInterest"])
    prev_day_px = float(ctx["prevDayPx"])
    day_ntl_vlm = float(ctx["dayNtlVlm"])
    day_base_vlm = float(ctx["dayBaseVlm"])

    return {
        "mark_price":             round(mark, 2),
        "oracle_price":           round(oracle, 2),
        "mid_price":              round(mid, 2),
        "premium_pct":            round((mark / oracle - 1) * 100, 4),
        "funding_rate_pct":       round(funding * 100, 4),
        "funding_rate_annual_pct": round(funding * 3 * 365 * 100, 2),
        "oi_btc":                 round(oi_btc, 2),
        "oi_usd_bn":              round(oi_btc * mark / 1e9, 3),
        "change_24h_pct":         round((mark / prev_day_px - 1) * 100, 2) if prev_day_px else 0,
        "volume_24h_usd_bn":      round(day_ntl_vlm / 1e9, 3),
        "volume_24h_btc":         round(day_base_vlm, 2),
    }


def get_funding_history(lookback_hours: int = 24) -> list[dict]:
    """
    Hourly BTC funding history.
    Each entry: {time_ms, funding_rate_pct, premium_pct}
    """
    now_ms = int(time.time() * 1000)
    raw = _post({"type": "fundingHistory", "coin": "BTC",
                 "startTime": now_ms - lookback_hours * 3_600_000})
    return [
        {
            "time_ms":          e["time"],
            "funding_rate_pct": round(float(e["fundingRate"]) * 100, 5),
            "premium_pct":      round(float(e["premium"]) * 100, 4),
        }
        for e in raw
    ]


def get_candles(interval: str = "1h", lookback_hours: int = 24) -> list[dict]:
    """
    OHLCV candles for BTC.
    interval: '1m', '5m', '15m', '1h', '4h', '1d'
    Each entry: {time_ms, open, high, low, close, volume_btc, trades}
    """
    now_ms = int(time.time() * 1000)
    raw = _post({
        "type": "candleSnapshot",
        "req": {"coin": "BTC", "interval": interval,
                "startTime": now_ms - lookback_hours * 3_600_000, "endTime": now_ms},
    })
    return [
        {
            "time_ms":    c["t"],
            "open":       float(c["o"]),
            "high":       float(c["h"]),
            "low":        float(c["l"]),
            "close":      float(c["c"]),
            "volume_btc": float(c["v"]),
            "trades":     c["n"],
        }
        for c in raw
    ]


def get_all_mids() -> dict[str, float]:
    """Mid prices for all Hyperliquid perp markets."""
    raw = _post({"type": "allMids"})
    return {k: float(v) for k, v in raw.items() if v}


# ---------------------------------------------------------------------------
# Account state (auth required)
# ---------------------------------------------------------------------------

def get_positions() -> list[dict]:
    """
    Open perp positions on the main account.
    Each entry: {coin, side, size, entry_price, mark_price,
                 unrealized_pnl, margin_used, leverage, liquidation_price}
    """
    state = _info().user_state(_main_addr())
    out = []
    for p in state.get("assetPositions", []):
        pos = p["position"]
        sz  = float(pos["szi"])
        if sz == 0:
            continue
        out.append({
            "coin":             pos["coin"],
            "side":             "long" if sz > 0 else "short",
            "size":             abs(sz),
            "entry_price":      round(float(pos["entryPx"]), 4) if pos.get("entryPx") else None,
            "mark_price":       round(float(pos["positionValue"]) / abs(sz), 4) if sz else None,
            "unrealized_pnl":   round(float(pos["unrealizedPnl"]), 4),
            "margin_used":      round(float(pos["marginUsed"]), 4),
            "leverage":         pos.get("leverage", {}).get("value"),
            "liquidation_price": round(float(pos["liquidationPx"]), 4) if pos.get("liquidationPx") else None,
        })
    return out


def get_open_orders() -> list[dict]:
    """
    Open orders on the main account.
    Each entry: {oid, coin, side, size, limit_px, order_type, reduce_only, timestamp_ms}
    """
    raw = _info().open_orders(_main_addr())
    return [
        {
            "oid":          o["oid"],
            "coin":         o["coin"],
            "side":         "buy" if o["side"] == "B" else "sell",
            "size":         float(o["sz"]),
            "limit_px":     float(o["limitPx"]),
            "order_type":   o.get("orderType", ""),
            "reduce_only":  o.get("reduceOnly", False),
            "timestamp_ms": o["timestamp"],
        }
        for o in raw
    ]


def get_account_summary() -> dict:
    """
    Account-level summary: equity, margin used, withdrawable USDC.
    """
    state = _info().user_state(_main_addr())
    ms = state["marginSummary"]
    return {
        "account_value":   round(float(ms["accountValue"]), 4),
        "total_margin_used": round(float(ms["totalMarginUsed"]), 4),
        "withdrawable":    round(float(state["withdrawable"]), 4),
        "positions":       len([p for p in state.get("assetPositions", [])
                                if float(p["position"]["szi"]) != 0]),
    }


# ---------------------------------------------------------------------------
# Trading (auth required — writes to exchange)
# ---------------------------------------------------------------------------

def set_leverage(coin: str, leverage: int, is_cross: bool = True) -> dict:
    """
    Set leverage for a coin. is_cross=True for cross-margin, False for isolated.
    Returns raw SDK response.
    """
    return _exchange().update_leverage(leverage, coin, is_cross=is_cross)


def place_market_order(coin: str, is_buy: bool, sz_usd: float,
                       slippage: float = 0.05) -> dict:
    """
    Open a market position.
    sz_usd: notional in USD (converted to coin qty at current mid price).
    slippage: max acceptable slippage fraction (default 5%).
    Returns: {status, oid, coin, side, size, filled_px} or {status, error}
    """
    sz = _sz_from_usd(coin, sz_usd)
    result = _exchange().market_open(coin, is_buy, sz, slippage=slippage)
    return _parse_order_result(result, coin, "buy" if is_buy else "sell", sz)


def place_limit_order(coin: str, is_buy: bool, sz_usd: float,
                      limit_px: float, reduce_only: bool = False) -> dict:
    """
    Place a limit order (GTC by default).
    sz_usd: notional in USD.
    Returns: {status, oid, coin, side, size, limit_px} or {status, error}
    """
    from hyperliquid.utils.signing import OrderType
    sz = _sz_from_usd(coin, sz_usd)
    order_type: OrderType = {"limit": {"tif": "Gtc"}}
    result = _exchange().order(coin, is_buy, sz, limit_px, order_type,
                               reduce_only=reduce_only)
    return _parse_order_result(result, coin, "buy" if is_buy else "sell", sz,
                               limit_px=limit_px)


def close_position(coin: str, slippage: float = 0.05) -> dict:
    """
    Market-close the full position for a coin.
    Returns: {status, oid, coin, side, size, filled_px} or {status, error}
    """
    result = _exchange().market_close(coin, slippage=slippage)
    return _parse_order_result(result, coin, side=None, sz=None)


def cancel_order(coin: str, oid: int) -> dict:
    """Cancel a single open order by order ID."""
    result = _exchange().cancel(coin, oid)
    if result.get("status") == "ok":
        return {"status": "ok", "cancelled_oid": oid, "coin": coin}
    return {"status": "err", "error": result}


def cancel_all_orders(coin: str | None = None) -> dict:
    """
    Cancel all open orders, optionally filtered to a single coin.
    Returns {status, cancelled_count}.
    """
    orders = get_open_orders()
    if coin:
        orders = [o for o in orders if o["coin"] == coin]
    if not orders:
        return {"status": "ok", "cancelled_count": 0}

    from hyperliquid.utils.types import CancelRequest
    cancels: list[CancelRequest] = [{"coin": o["coin"], "oid": o["oid"]} for o in orders]
    result = _exchange().bulk_cancel(cancels)
    if result.get("status") == "ok":
        return {"status": "ok", "cancelled_count": len(cancels)}
    return {"status": "err", "error": result}


# ---------------------------------------------------------------------------
# Internal response parser
# ---------------------------------------------------------------------------

def _parse_order_result(result: dict, coin: str, side: str | None,
                        sz: float | None, limit_px: float | None = None) -> dict:
    if result.get("status") != "ok":
        return {"status": "err", "error": result.get("response", result)}

    statuses = (result.get("response", {})
                      .get("data", {})
                      .get("statuses", [{}]))
    s = statuses[0] if statuses else {}

    if "error" in s:
        return {"status": "err", "error": s["error"]}

    filled = s.get("filled", {})
    resting = s.get("resting", {})

    out: dict = {"status": "ok", "coin": coin}
    if side:
        out["side"] = side
    if sz is not None:
        out["size"] = sz
    if limit_px is not None:
        out["limit_px"] = limit_px
    if filled:
        out["oid"]       = filled.get("oid")
        out["filled_px"] = round(float(filled["avgPx"]), 4) if filled.get("avgPx") else None
        out["filled_sz"] = float(filled.get("totalSz", sz or 0))
    elif resting:
        out["oid"]   = resting.get("oid")
        out["state"] = "resting"
    return out


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Run as module to avoid shadowing the installed SDK:
    #   python3 -m skills.staging.hyperliquid  (from bastobot root)
    import json

    print("=== BTC Perp Snapshot ===")
    print(json.dumps(get_btc_perp(), indent=2))

    print("\n=== Account Summary ===")
    print(json.dumps(get_account_summary(), indent=2))

    print("\n=== Open Positions ===")
    pos = get_positions()
    print(json.dumps(pos, indent=2) if pos else "  none")

    print("\n=== Open Orders ===")
    orders = get_open_orders()
    print(json.dumps(orders, indent=2) if orders else "  none")

    print("\n=== Funding History (last 4h) ===")
    for e in get_funding_history(lookback_hours=4)[-4:]:
        print(f"  {e['funding_rate_pct']:+.5f}%  premium {e['premium_pct']:+.4f}%")

    print("\n=== Last 3 Hourly Candles ===")
    for c in get_candles("1h", lookback_hours=4)[-3:]:
        print(f"  O:{c['open']:,.0f}  H:{c['high']:,.0f}  L:{c['low']:,.0f}  "
              f"C:{c['close']:,.0f}  V:{c['volume_btc']:.1f} BTC")
