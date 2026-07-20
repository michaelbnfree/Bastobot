import os
import time
import requests
import numpy as np
import pandas as pd
import redis as _redis_lib
from datetime import datetime, date, timezone
from tradingview_ta import TA_Handler, Interval
from dotenv import load_dotenv

_r = _redis_lib.Redis(host="localhost", port=6379, db=0)

# TradingView rate limits
_TV_USER_DAILY_LIMIT = 4  # User-requested calls per day
_TV_FALLBACK_HOURLY_LIMIT = 15  # Automatic fallback per hour (circuit breaker if exceeded)
_TV_FALLBACK_CIRCUIT_THRESHOLD = 10  # Consecutive fallbacks → alert (local is broken)

_TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TG_CHAT = int(os.getenv("TELEGRAM_CHAT_ID", 0))

_INTERVAL_MAP = {
    "5m":  Interval.INTERVAL_5_MINUTES,
    "15m": Interval.INTERVAL_15_MINUTES,
    "30m": Interval.INTERVAL_30_MINUTES,
    "1h":  Interval.INTERVAL_1_HOUR,
    "4h":  Interval.INTERVAL_4_HOURS,
    "1d":  Interval.INTERVAL_1_DAY,
    "1w":  Interval.INTERVAL_1_WEEK,
}

load_dotenv('/root/bastobot/.env')

COINGLASS_KEY = os.getenv("COINGLASS_API_KEY")
SOSOVALUE_KEY = os.getenv("SOSOVALUE_API_KEY")


def _get_binance_price():
    # 24hr ticker for spot price + 24h stats
    r = requests.get("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT", timeout=10)
    d = r.json()

    # Daily klines for 7d change and volume % change (last 9 days covers full days + current)
    klines = requests.get(
        "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=9", timeout=10
    ).json()
    price_7d_ago = float(klines[0][4])            # close 7 complete days ago
    vol_yesterday = float(klines[-2][7])           # quoteAssetVolume = USDT volume
    vol_day_before = float(klines[-3][7])
    vol_change_pct = (vol_yesterday / vol_day_before - 1) * 100 if vol_day_before else 0

    return {
        "price": float(d["lastPrice"]),
        "change_24h_pct": float(d["priceChangePercent"]),
        "change_7d_pct": round((float(d["lastPrice"]) / price_7d_ago - 1) * 100, 2),
        "high_24h": float(d["highPrice"]),
        "low_24h": float(d["lowPrice"]),
        "volume_24h_usdt": float(d["quoteVolume"]),
        "volume_yesterday_usdt": vol_yesterday,
        "volume_change_pct": round(vol_change_pct, 1),
    }


def _calculate_rsi(prices, period=14):
    """Calculate RSI using SMA smoothing (matches TradingView default)."""
    if len(prices) < period + 1:
        return None
    prices = np.array(prices, dtype=float)
    deltas = np.diff(prices)

    # Separate up and down moves
    up = np.where(deltas > 0, deltas, 0)
    down = np.where(deltas < 0, -deltas, 0)

    # Use simple moving average (SMA) smoothing, not Wilder's
    # This matches TradingView's default RSI calculation
    up_sma = np.convolve(up, np.ones(period)/period, mode='valid')
    down_sma = np.convolve(down, np.ones(period)/period, mode='valid')

    if down_sma[-1] == 0:
        return 100.0 if up_sma[-1] > 0 else 0.0

    rs = up_sma[-1] / down_sma[-1]
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return round(rsi, 2)


def _calculate_bollinger_bands(prices, period=20, num_std=2):
    """Calculate Bollinger Bands (20 SMA, 2 stdev)."""
    if len(prices) < period:
        return None, None, None
    prices = np.array(prices, dtype=float)
    sma = np.mean(prices[-period:])
    std = np.std(prices[-period:])
    bb_upper = round(sma + (num_std * std), 2)
    bb_lower = round(sma - (num_std * std), 2)
    bb_basis = round(sma, 2)
    return bb_upper, bb_basis, bb_lower


def _get_local_indicators(symbol, candles=None):
    """Compute indicators locally from Binance candles (primary path, no external API)."""
    pair = f"{symbol}USDT"
    tfs = candles or ("1h", "4h", "1d")
    results = {}

    interval_map = {"1h": "1h", "4h": "4h", "1d": "1d"}
    candle_counts = {"1h": 300, "4h": 300, "1d": 100}

    for tf in tfs:
        if tf not in interval_map:
            continue
        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": pair, "interval": tf, "limit": candle_counts[tf]},
                timeout=10
            )
            klines = resp.json()
            if not klines:
                continue

            # Include current forming candle for live momentum (matches TradingView default)
            closes = [float(k[4]) for k in klines]
            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]

            rsi = _calculate_rsi(closes, 14)
            bb_upper, bb_basis, bb_lower = _calculate_bollinger_bands(closes, 20, 2)

            if rsi is not None and bb_upper is not None:
                results[tf] = {
                    "summary": {"RECOMMENDATION": "NEUTRAL", "BUY": 0, "SELL": 0, "NEUTRAL": 0},
                    "rsi": rsi,
                    "macd": 0,
                    "macd_signal": 0,
                    "adx": 0,
                    "ema_20": 0,
                    "ema_50": 0,
                    "ema_200": 0,
                    "bb_upper": bb_upper,
                    "bb_lower": bb_lower,
                    "bb_basis": bb_basis,
                }
        except Exception as e:
            print(f"[TA-LOCAL] {tf} fetch failed: {e}")

    return results if results else None


def _send_telegram_alert(text: str) -> None:
    """Send Telegram alert for rate limit hits."""
    if not _TG_TOKEN or not _TG_CHAT:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
            json={"chat_id": _TG_CHAT, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        print(f"[TG-ALERT] Failed to send: {e}")


def _check_tv_user_request_limit(symbol: str, user_id: str = "manual") -> tuple[bool, int]:
    """
    Check if user-requested TV call is allowed. Returns (allowed, remaining_today).
    Increments counter only if allowed. Sends alert if limit hit.
    """
    today = date.today().isoformat()
    key = f"tv_user_calls:{today}"

    current_calls = int(_r.get(key) or 0)
    remaining = _TV_USER_DAILY_LIMIT - current_calls

    if current_calls >= _TV_USER_DAILY_LIMIT:
        msg = f"⚠️ *TradingView API limit hit*\n{_TV_USER_DAILY_LIMIT}/day cap reached.\nTry again tomorrow or use local indicators."
        print(f"[TV-USER-LIMIT] Daily cap hit ({_TV_USER_DAILY_LIMIT}/day). User {user_id} rejected for {symbol}.")
        _send_telegram_alert(msg)
        return False, 0

    _r.incr(key)
    _r.expire(key, 86400)
    remaining = _TV_USER_DAILY_LIMIT - (current_calls + 1)
    print(f"[TV-USER-REQUEST] {user_id} requesting {symbol} ({remaining} remaining today)")
    return True, remaining


def _check_tv_fallback_hourly_limit(symbol: str) -> bool:
    """
    Check if automatic fallback is allowed this hour. Returns True if allowed.
    Enforces {_TV_FALLBACK_HOURLY_LIMIT} per hour to detect broken local pipeline.
    """
    now = datetime.now(timezone.utc)
    hour_key = f"tv_fallback:hour:{now.strftime('%Y-%m-%d-%H')}"

    current_hour_calls = int(_r.get(hour_key) or 0)

    if current_hour_calls >= _TV_FALLBACK_HOURLY_LIMIT:
        print(f"[TV-FALLBACK-LIMIT] Hourly cap hit ({_TV_FALLBACK_HOURLY_LIMIT}/hour) for {symbol}. Local pipeline may be broken.")
        return False

    _r.incr(hour_key)
    _r.expire(hour_key, 3600)  # 1-hour TTL
    return True


def _track_fallback_consecutive(symbol: str, success: bool) -> int:
    """Track consecutive fallback triggers. Returns current consecutive count."""
    key = f"tv_fallback:consecutive"

    if success:
        # Reset on success
        _r.delete(key)
        return 0
    else:
        # Increment on fallback
        count = int(_r.incr(key) or 0)
        _r.expire(key, 3600)  # Reset if no fallback for 1 hour
        return count


def _check_fallback_circuit_breaker(symbol: str, consecutive: int) -> None:
    """Alert if consecutive fallbacks indicate broken local pipeline."""
    if consecutive >= _TV_FALLBACK_CIRCUIT_THRESHOLD:
        msg = (
            f"🚨 *Local indicators failing*\n"
            f"{consecutive} consecutive TradingView fallbacks for {symbol}.\n"
            f"Local Binance fetch is likely broken. Check scanner logs."
        )
        print(f"[CIRCUIT-BREAKER] {consecutive} consecutive fallbacks for {symbol} — alerting!")
        _send_telegram_alert(msg)


def _get_tv_indicators_internal(symbol, candles=None) -> dict | None:
    """Internal TradingView fetch (no limit). Used by automatic fallback and user requests."""
    pair = f"{symbol}USDT"
    tfs = [(c, _INTERVAL_MAP[c]) for c in (candles or ("1h", "4h", "1d")) if c in _INTERVAL_MAP]
    results = {}
    for i, (label, interval) in enumerate(tfs):
        if i > 0:
            time.sleep(4)  # Delay between requests to respect rate limits

        retry_delay = 5
        max_retries = 2
        for attempt in range(max_retries):
            try:
                h = TA_Handler(symbol=pair, screener="crypto", exchange="BINANCE", interval=interval)
                a = h.get_analysis()
                bb_upper = a.indicators.get("BB.upper")
                bb_lower = a.indicators.get("BB.lower")
                bb_basis = round((bb_upper + bb_lower) / 2, 2) if bb_upper and bb_lower else None
                results[label] = {
                    "summary": a.summary,
                    "rsi": round(a.indicators["RSI"], 2),
                    "macd": round(a.indicators["MACD.macd"], 4),
                    "macd_signal": round(a.indicators["MACD.signal"], 4),
                    "adx": round(a.indicators["ADX"], 2),
                    "ema_20": round(a.indicators["EMA20"], 2),
                    "ema_50": round(a.indicators["EMA50"], 2),
                    "ema_200": round(a.indicators["EMA200"], 2),
                    "bb_upper": round(bb_upper, 2) if bb_upper else None,
                    "bb_lower": round(bb_lower, 2) if bb_lower else None,
                    "bb_basis": bb_basis,
                }
                break  # Success, exit retry loop
            except Exception as e:
                if "429" in str(e) and attempt < max_retries - 1:
                    print(f"[TA] {label} rate limited, retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    print(f"[TA] {label} fetch failed, skipping: {e}")
                    break
    return results


def get_tv_indicators_user_request(symbol: str, candles=None, user_id: str = "manual") -> dict | None:
    """
    User-requested TradingView data (e.g., via Telegram /tv command).
    Subject to 4-call/day hard limit with Telegram alerts.
    Returns None if limit exceeded.
    """
    allowed, remaining = _check_tv_user_request_limit(symbol, user_id)
    if not allowed:
        return None
    return _get_tv_indicators_internal(symbol, candles)


def _get_tv_indicators_fallback(symbol, candles=None):
    """
    TradingView automatic fallback (hourly cap 15/hour, circuit breaker at 10 consecutive).
    Called if local indicators fail. Logs every trigger for visibility into degradation.
    """
    # Log every fallback trigger (not just failures)
    print(f"[TV-FALLBACK] Local indicators failed for {symbol}, attempting TradingView fallback...")

    # Check hourly rate limit
    if not _check_tv_fallback_hourly_limit(symbol):
        consecutive = _track_fallback_consecutive(symbol, False)
        _check_fallback_circuit_breaker(symbol, consecutive)
        return None

    # Attempt fetch
    result = _get_tv_indicators_internal(symbol, candles)

    if result:
        # Success — reset consecutive counter
        _track_fallback_consecutive(symbol, True)
        print(f"[TV-FALLBACK] Success for {symbol}")
        return result
    else:
        # Failed — track consecutive failures
        consecutive = _track_fallback_consecutive(symbol, False)
        _check_fallback_circuit_breaker(symbol, consecutive)
        print(f"[TV-FALLBACK] Failed for {symbol} ({consecutive} consecutive)")
        return None


def _get_fear_greed():
    r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
    d = r.json()["data"][0]
    return {"score": int(d["value"]), "label": d["value_classification"]}


def _get_coingecko_global():
    r = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
    d = r.json()["data"]
    return {
        "btc_dominance_pct": round(d["market_cap_percentage"]["btc"], 1),
        "total_market_cap_usd": d["total_market_cap"]["usd"],
        "total_volume_24h_usd": d["total_volume"]["usd"],
    }


def _get_polymarket_btc():
    import json as _json
    r = requests.get(
        "https://gamma-api.polymarket.com/markets"
        "?closed=false&tag=crypto&order=volume24hr&ascending=false",
        timeout=15,
    )
    markets = r.json() if isinstance(r.json(), list) else []
    btc = [
        m for m in markets
        if ("bitcoin" in m.get("question", "").lower() or "btc" in m.get("question", "").lower())
        and m.get("outcomePrices")
    ][:6]
    results = []
    for m in btc:
        try:
            prices = m["outcomePrices"]
            if isinstance(prices, str):
                prices = _json.loads(prices)
            yes_prob = float(prices[0])
            results.append({"question": m["question"], "yes_prob": yes_prob})
        except (ValueError, IndexError, TypeError):
            pass
    return results


def _get_derivatives():
    """Binance Futures: funding, OI + 24h % change, L/S ratios, taker volume."""
    BASE = "https://fapi.binance.com"
    out = {}

    r = requests.get(f"{BASE}/fapi/v1/premiumIndex?symbol=BTCUSDT", timeout=10)
    d = r.json()
    out["funding_rate_pct"] = round(float(d["lastFundingRate"]) * 100, 4)
    out["mark_price"] = round(float(d["markPrice"]), 2)
    out["index_price"] = round(float(d["indexPrice"]), 2)
    out["premium_pct"] = round((float(d["markPrice"]) / float(d["indexPrice"]) - 1) * 100, 4)

    r = requests.get(f"{BASE}/fapi/v1/openInterest?symbol=BTCUSDT", timeout=10)
    out["oi_contracts"] = round(float(r.json()["openInterest"]), 0)

    # 25 hourly points = ~24h of history
    r = requests.get(
        f"{BASE}/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=25", timeout=10
    )
    oi_hist = r.json()
    oi_now_bn = round(float(oi_hist[-1]["sumOpenInterestValue"]) / 1e9, 2)
    oi_24h_bn = round(float(oi_hist[0]["sumOpenInterestValue"]) / 1e9, 2)
    out["oi_usd_bn"] = oi_now_bn
    out["oi_change_24h_pct"] = round((oi_now_bn / oi_24h_bn - 1) * 100, 2) if oi_24h_bn else 0
    out["oi_hist_6h_bn"] = [round(float(x["sumOpenInterestValue"]) / 1e9, 2) for x in oi_hist[-6:]]
    out["oi_trend"] = "rising" if oi_now_bn > oi_24h_bn else "falling"

    r = requests.get(
        f"{BASE}/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=1",
        timeout=10,
    )
    d = r.json()[0]
    out["global_ls_ratio"] = float(d["longShortRatio"])
    out["global_longs_pct"] = round(float(d["longAccount"]) * 100, 1)
    out["global_shorts_pct"] = round(float(d["shortAccount"]) * 100, 1)

    r = requests.get(
        f"{BASE}/futures/data/topLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=1",
        timeout=10,
    )
    d = r.json()[0]
    out["top_trader_ls_ratio"] = float(d["longShortRatio"])
    out["top_trader_longs_pct"] = round(float(d["longAccount"]) * 100, 1)
    out["top_trader_shorts_pct"] = round(float(d["shortAccount"]) * 100, 1)

    r = requests.get(
        f"{BASE}/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=1h&limit=1",
        timeout=10,
    )
    out["taker_buy_sell_ratio"] = float(r.json()[0]["buySellRatio"])

    return out


def _get_bybit():
    r = requests.get(
        "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT", timeout=10
    )
    d = r.json()["result"]["list"][0]
    ls = requests.get(
        "https://api.bybit.com/v5/market/account-ratio?category=linear&symbol=BTCUSDT&period=1h&limit=1",
        timeout=10,
    )
    ls_d = ls.json()["result"]["list"][0]
    return {
        "funding_rate_pct": round(float(d["fundingRate"]) * 100, 4),
        "mark_price": round(float(d["markPrice"]), 2),
        "oi_usd_bn": round(float(d["openInterestValue"]) / 1e9, 2),
        "longs_pct": round(float(ls_d["buyRatio"]) * 100, 1),
        "shorts_pct": round(float(ls_d["sellRatio"]) * 100, 1),
    }


def _get_okx():
    fr_d = requests.get(
        "https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP", timeout=10
    ).json()["data"][0]
    oi_d = requests.get(
        "https://www.okx.com/api/v5/public/open-interest?instType=SWAP&uly=BTC-USDT", timeout=10
    ).json()["data"][0]
    ls_val = float(requests.get(
        "https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=1H&limit=1",
        timeout=10,
    ).json()["data"][0][1])
    longs_pct = round(ls_val / (1 + ls_val) * 100, 1)
    return {
        "funding_rate_pct": round(float(fr_d["fundingRate"]) * 100, 4),
        "oi_usd_bn": round(float(oi_d["oiUsd"]) / 1e9, 2),
        "ls_ratio": round(ls_val, 3),
        "longs_pct": longs_pct,
        "shorts_pct": round(100 - longs_pct, 1),
    }


def _get_liquidations():
    """OKX + Gate.io liquidation orders — 24h long/short volumes, % change, price clusters."""
    now_ms = int(time.time() * 1000)
    now_s = int(time.time())
    period_24h = 86_400_000
    period_12h = period_24h // 2

    def _parse_okx(since_ms):
        long_usd = short_usd = 0.0
        buckets: dict[int, float] = {}
        r = requests.get(
            "https://www.okx.com/api/v5/public/liquidation-orders"
            "?instType=SWAP&uly=BTC-USDT&state=filled&limit=100",
            timeout=10,
        )
        # BTC-USDT-SWAP: sz is in contracts, ctVal = 0.01 BTC per contract
        CT_VAL = 0.01
        for order in r.json().get("data", []):
            for d in order.get("details", []):
                if int(d["ts"]) < since_ms:
                    continue
                px = float(d["bkPx"])
                usd_val = float(d["sz"]) * CT_VAL * px
                bucket = int(px // 500) * 500
                buckets[bucket] = buckets.get(bucket, 0) + usd_val
                if d["posSide"] == "long":
                    long_usd += usd_val
                else:
                    short_usd += usd_val
        return long_usd, short_usd, buckets

    # Hard bounds on BTC liquidation prices — anything outside is bad data
    BTC_PRICE_MIN = 5_000
    BTC_PRICE_MAX = 500_000

    def _parse_gateio(from_s, to_s):
        long_usd = short_usd = 0.0
        buckets: dict[int, float] = {}
        skipped = 0
        window_end = to_s
        window_start = max(from_s, to_s - 3600)
        r = requests.get(
            f"https://api.gateio.ws/api/v4/futures/usdt/liq_orders"
            f"?contract=BTC_USDT&from={window_start}&to={window_end}&limit=100",
            timeout=10,
        )
        QUANTO = 0.0001  # each contract = 0.0001 BTC
        for o in (r.json() if isinstance(r.json(), list) else []):
            px = float(o.get("fill_price") or o.get("order_price") or 0)
            raw_size = float(o.get("size", 0))
            if not px or not raw_size:
                continue
            if not (BTC_PRICE_MIN <= px <= BTC_PRICE_MAX):
                skipped += 1
                continue
            usd_val = abs(raw_size) * QUANTO * px
            bucket = int(px // 500) * 500
            buckets[bucket] = buckets.get(bucket, 0) + usd_val
            if raw_size > 0:
                long_usd += usd_val
            else:
                short_usd += usd_val
        if skipped:
            print(f"[LIQ] Gate.io: skipped {skipped} orders with out-of-bounds price")
        return long_usd, short_usd, buckets

    # Current 24h window
    ll, ls, lb = _parse_okx(now_ms - period_24h)
    gl, gs, gb = _parse_gateio(now_s - 86400, now_s)

    # Cross-source consistency check — if one source is >10x the other, exclude the outlier
    okx_total  = ll + ls
    gate_total = gl + gs
    gate_excluded = False
    if okx_total > 0 and gate_total > 0:
        ratio = max(okx_total, gate_total) / min(okx_total, gate_total)
        if ratio > 10:
            # Trust OKX; zero out Gate.io contribution
            gl = gs = 0.0
            gb = {}
            gate_excluded = True
            print(f"[LIQ] Gate.io excluded: ratio vs OKX={ratio:.1f}x (okx=${okx_total:,.0f}  gate=${gate_total:,.0f})")

    total_long  = ll + gl
    total_short = ls + gs

    # Previous 24h window (for % change) — only OKX has enough data
    pl, ps, _ = _parse_okx(now_ms - period_24h * 2)
    prev_total = pl + ps
    curr_total = total_long + total_short
    change_pct = round((curr_total / prev_total - 1) * 100, 1) if prev_total else None

    # Merge price buckets
    all_buckets: dict[int, float] = {}
    for b, v in {**lb, **gb}.items():
        all_buckets[b] = all_buckets.get(b, 0) + v
    top_zones = sorted(all_buckets.items(), key=lambda x: x[1], reverse=True)[:3]
    clusters = [f"${z:,}–${z+500:,} (${v:,.0f})" for z, v in top_zones]

    return {
        "longs_liq_usd":   round(total_long),
        "shorts_liq_usd":  round(total_short),
        "total_liq_usd":   round(curr_total),
        "change_pct":      change_pct,
        "top_liq_zones":   clusters,
        "okx_liq_usd":     round(okx_total),
        "gate_liq_usd":    round(gate_total),
        "gate_excluded":   gate_excluded,
    }


def _get_coinglass():
    if not COINGLASS_KEY:
        return None
    headers = {"coinglassSecret": COINGLASS_KEY}
    out = {}
    for key, url in [
        ("funding", "https://open-api.coinglass.com/public/v2/indicator/funding?symbol=BTC"),
        ("open_interest", "https://open-api.coinglass.com/public/v2/indicator/open_interest?symbol=BTC"),
    ]:
        try:
            d = requests.get(url, headers=headers, timeout=10).json()
            if d.get("success"):
                out[key] = d.get("data")
        except Exception:
            pass
    return out if out else None


def _get_sosovalue():
    # Demo plan: 10 calls/month, 1 req/min — cache aggressively in Redis
    if not SOSOVALUE_KEY:
        return None
    import redis as _redis, json as _json
    _r = _redis.Redis(host='localhost', port=6379, db=0)
    CACHE_KEY = "sosovalue:etf_flows"
    CACHE_TTL = 60 * 60 * 72  # 72h — ~10 calls/month max

    cached = _r.get(CACHE_KEY)
    if cached:
        return _json.loads(cached)

    try:
        r = requests.get(
            "https://api.sosovalue.xyz/api/spot-bitcoin-etf/total-daily-net-inflow",
            headers={"Authorization": f"Bearer {SOSOVALUE_KEY}"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            _r.setex(CACHE_KEY, CACHE_TTL, _json.dumps(data))
            return data
    except Exception:
        pass
    return None


def get_btc_analysis(candles=None):
    result = {}
    sources = [
        ("binance", _get_binance_price),
        ("ta", lambda: _get_local_indicators("BTC", candles) or _get_tv_indicators_fallback("BTC", candles)),
        ("derivatives", _get_derivatives),
        ("bybit", _get_bybit),
        ("okx", _get_okx),
        ("liquidations", _get_liquidations),
        ("fear_greed", _get_fear_greed),
        ("market", _get_coingecko_global),
        ("polymarket", _get_polymarket_btc),
        ("coinglass", _get_coinglass),
        ("sosovalue", _get_sosovalue),
    ]
    for key, fn in sources:
        try:
            val = fn()
            if val is not None:
                result[key] = val
        except Exception as e:
            result[f"{key}_error"] = str(e)
    return result


def get_asset_analysis(symbol: str, candles=None) -> dict:
    """Generic analysis for any crypto asset — spot price, multi-TF TA, basic futures."""
    sym = symbol.upper()
    pair = f"{sym}USDT"
    result = {}

    # Spot price
    try:
        d = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={pair}", timeout=10).json()
        klines = requests.get(
            f"https://api.binance.com/api/v3/klines?symbol={pair}&interval=1d&limit=9", timeout=10
        ).json()
        price_7d_ago = float(klines[0][4])
        vol_yesterday = float(klines[-2][7])
        vol_day_before = float(klines[-3][7])
        vol_change_pct = (vol_yesterday / vol_day_before - 1) * 100 if vol_day_before else 0
        result["binance"] = {
            "price": float(d["lastPrice"]),
            "change_24h_pct": float(d["priceChangePercent"]),
            "change_7d_pct": round((float(d["lastPrice"]) / price_7d_ago - 1) * 100, 2),
            "high_24h": float(d["highPrice"]),
            "low_24h": float(d["lowPrice"]),
            "volume_24h_usdt": float(d["quoteVolume"]),
            "volume_yesterday_usdt": vol_yesterday,
            "volume_change_pct": round(vol_change_pct, 1),
        }
    except Exception as e:
        result["binance_error"] = str(e)

    # Multi-TF TA (Local Binance candles primary, TradingView fallback)
    try:
        ta_results = _get_local_indicators(sym, candles) or _get_tv_indicators_fallback(sym, candles)
        result["ta"] = ta_results if ta_results else {}
    except Exception as e:
        result["ta_error"] = str(e)

    # Binance Futures (funding, OI, L/S) — skip silently if perp doesn't exist
    try:
        BASE = "https://fapi.binance.com"
        d = requests.get(f"{BASE}/fapi/v1/premiumIndex?symbol={pair}", timeout=10).json()
        if "lastFundingRate" in d:
            out = {
                "funding_rate_pct": round(float(d["lastFundingRate"]) * 100, 4),
                "mark_price": round(float(d["markPrice"]), 2),
            }
            oi = requests.get(f"{BASE}/fapi/v1/openInterest?symbol={pair}", timeout=10).json()
            out["oi_contracts"] = round(float(oi["openInterest"]), 0)

            oi_hist = requests.get(
                f"{BASE}/futures/data/openInterestHist?symbol={pair}&period=1h&limit=25", timeout=10
            ).json()
            oi_now = round(float(oi_hist[-1]["sumOpenInterestValue"]) / 1e9, 2)
            oi_24h = round(float(oi_hist[0]["sumOpenInterestValue"]) / 1e9, 2)
            out["oi_usd_bn"] = oi_now
            out["oi_change_24h_pct"] = round((oi_now / oi_24h - 1) * 100, 2) if oi_24h else 0

            ls = requests.get(
                f"{BASE}/futures/data/globalLongShortAccountRatio?symbol={pair}&period=1h&limit=1",
                timeout=10,
            ).json()[0]
            out["global_ls_ratio"] = float(ls["longShortRatio"])
            out["global_longs_pct"] = round(float(ls["longAccount"]) * 100, 1)
            out["global_shorts_pct"] = round(float(ls["shortAccount"]) * 100, 1)
            result["derivatives"] = out
    except Exception:
        pass

    # Fear & Greed + global market (asset-agnostic)
    try:
        result["fear_greed"] = _get_fear_greed()
    except Exception:
        pass
    try:
        result["market"] = _get_coingecko_global()
    except Exception:
        pass

    return result
