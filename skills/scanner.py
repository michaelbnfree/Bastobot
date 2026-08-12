"""
Background market data cache and alert engine.
Fetches data for all watched assets, stores in Redis,
and fires Telegram alerts when alert conditions are met with cooldowns.
"""

import sys
import json
import time
import requests
import redis as _redis_lib
from datetime import datetime, timezone

sys.path.insert(0, "/root/bastobot")

_r = _redis_lib.Redis(host="localhost", port=6379, db=0)

_CACHE_KEY = "scanner:cache:{symbol}"
_CACHE_TTL = 900   # 15 min — TV rate limit: only refresh every 3rd 5-min cycle
_FETCH_SLEEP = 8   # seconds between asset fetches to avoid TV 429s
_ALERT_KEY = "scanner:alert:{symbol}:{condition}"
_PREV_PRICE_KEY = "scanner:prev_price:{symbol}"

# Telegram outbound (same bot, same authorized user as the gateway)
_TG_TOKEN = "***REDACTED_TELEGRAM_TOKEN***"
_TG_CHAT  = 298886049


def send_alert(text: str) -> None:
    try:
        requests.post(
            f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
            json={"chat_id": _TG_CHAT, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        print(f"[ALERT] Sent: {text[:60]}")
    except Exception as e:
        print(f"[ALERT] TG failed: {e}")


def _cooldown(symbol: str, condition: str, ttl: int) -> bool:
    """True = still in cooldown. Sets the key on first call so next call within TTL is blocked."""
    key = _ALERT_KEY.format(symbol=symbol, condition=condition)
    if _r.get(key):
        return True
    _r.setex(key, ttl, "1")
    return False


def fetch_and_cache(symbol: str, candles: tuple = ("1h", "4h", "1d")) -> dict | None:
    from skills.trading import get_btc_analysis, get_asset_analysis
    from skills.dexscreener_client import DexScreenerClient

    try:
        data = get_btc_analysis(candles=candles) if symbol == "BTC" else get_asset_analysis(symbol, candles=candles)

        # Fetch DEX prices for CEX/DEX comparison
        dex_client = DexScreenerClient()
        cex_price = data.get("binance", {}).get("price")
        if cex_price:
            try:
                dex_comparison = dex_client.compare_dex_cex_prices(symbol, cex_price)
                data["dex_comparison"] = dex_comparison
                if dex_comparison.get("arbitrage_pct") and abs(dex_comparison["arbitrage_pct"]) >= 0.5:
                    print(f"[DEX] {symbol}: {dex_comparison['arbitrage_pct']:+.2f}% arb opportunity")
            except Exception as e:
                print(f"[SCANNER] DEX fetch for {symbol} failed: {e}")
                data["dex_comparison"] = {"error": str(e)}

        _r.setex(
            _CACHE_KEY.format(symbol=symbol),
            _CACHE_TTL,
            json.dumps({"data": data, "symbol": symbol, "fetched": datetime.now(timezone.utc).isoformat()}),
        )
        return data
    except Exception as e:
        print(f"[SCANNER] fetch_and_cache({symbol}) failed: {e}")
        return None


def _has_valid_indicators(data: dict) -> bool:
    """Check if cached data has required indicators (RSI, Bollinger bands)."""
    if not data:
        return False

    ta = data.get("ta")
    if not ta:
        return False

    for tf in ["1h", "4h", "1d"]:
        if tf not in ta:
            return False
        ind = ta[tf]
        if not ind.get("rsi") or not ind.get("bb_upper") or not ind.get("bb_lower"):
            print(f"[SCANNER] Invalid indicators for {tf}: RSI={ind.get('rsi')}, BB={ind.get('bb_upper')}")
            return False
    return True


def get_cached(symbol: str) -> dict | None:
    raw = _r.get(_CACHE_KEY.format(symbol=symbol))
    if not raw:
        return None
    data = json.loads(raw).get("data")

    if not _has_valid_indicators(data):
        print(f"[SCANNER] Cache validation failed for {symbol} — forcing refresh")
        return None

    return data


def cache_age_seconds(symbol: str) -> float | None:
    """Returns how old the cache entry is in seconds, or None if no cache."""
    raw = _r.get(_CACHE_KEY.format(symbol=symbol))
    if not raw:
        return None
    fetched = json.loads(raw).get("fetched")
    if not fetched:
        return None
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(fetched)).total_seconds()
        return age
    except Exception:
        return None


def get_or_fetch(symbol: str, candles: tuple = ("1h", "4h", "1d")) -> dict | None:
    data = get_cached(symbol)
    return data if data is not None else fetch_and_cache(symbol, candles=candles)


def check_alerts(symbol: str, data: dict) -> list[str]:
    """Evaluate all alert conditions. Returns list of condition names that fired."""
    from skills.conviction import score as conv_score

    fired:   list[str] = []
    ta      = data.get("ta", {})
    deriv   = data.get("derivatives", {})
    bybit   = data.get("bybit", {})
    okx     = data.get("okx", {})
    fg      = data.get("fear_greed", {})
    binance = data.get("binance", {})
    price   = binance.get("price", 0)

    conviction = conv_score(data, symbol)
    cv_label   = conviction["label"]
    cv_score   = conviction["score"]
    direction  = conviction["direction"].capitalize()

    # ── Multi-TF RSI extreme oversold ────────────────────────────────────────
    rsi_extremes = [
        f"{tf} RSI {ta.get(tf, {}).get('rsi', 0):.0f}"
        for tf in ("1h", "4h", "1d")
        if ta.get(tf, {}).get("rsi") and ta[tf]["rsi"] <= 20
    ]
    if len(rsi_extremes) >= 2 and not _cooldown(symbol, "rsi_extreme_oversold", 14400):
        send_alert(
            f"🔴 *{symbol} RSI Extreme Oversold*\n"
            f"{' | '.join(rsi_extremes)}\n"
            f"Conviction: {cv_label} ({cv_score}/10) — {direction}\n"
            f"Price: ${price:,.2f}"
        )
        fired.append("rsi_extreme_oversold")

    # ── Multi-TF RSI extreme overbought ──────────────────────────────────────
    rsi_ob = [
        f"{tf} RSI {ta.get(tf, {}).get('rsi', 0):.0f}"
        for tf in ("1h", "4h", "1d")
        if ta.get(tf, {}).get("rsi") and ta[tf]["rsi"] >= 80
    ]
    if len(rsi_ob) >= 2 and not _cooldown(symbol, "rsi_extreme_overbought", 14400):
        send_alert(
            f"🟢 *{symbol} RSI Extreme Overbought*\n"
            f"{' | '.join(rsi_ob)}\n"
            f"Conviction: {cv_label} ({cv_score}/10) — {direction}\n"
            f"Price: ${price:,.2f}"
        )
        fired.append("rsi_extreme_overbought")

    # ── Daily EMA200 cross ────────────────────────────────────────────────────
    ema200 = ta.get("1d", {}).get("ema_200")
    if ema200 and price:
        prev_raw   = _r.get(_PREV_PRICE_KEY.format(symbol=symbol))
        prev_price = float(prev_raw) if prev_raw else None
        if prev_price:
            if prev_price < ema200 <= price and not _cooldown(symbol, "ema200_cross_up", 86400):
                send_alert(
                    f"📈 *{symbol} crossed above daily EMA200*\n"
                    f"EMA200: ${ema200:,.2f}  |  Price: ${price:,.2f}"
                )
                fired.append("ema200_cross_up")
            elif prev_price > ema200 >= price and not _cooldown(symbol, "ema200_cross_down", 86400):
                send_alert(
                    f"📉 *{symbol} crossed below daily EMA200*\n"
                    f"EMA200: ${ema200:,.2f}  |  Price: ${price:,.2f}"
                )
                fired.append("ema200_cross_down")
        _r.setex(_PREV_PRICE_KEY.format(symbol=symbol), 86400, str(price))

    # ── Funding rate extremes ─────────────────────────────────────────────────
    funding_rates = [
        src.get("funding_rate_pct")
        for src in (deriv, bybit, okx)
        if src.get("funding_rate_pct") is not None
    ]
    if funding_rates:
        avg_fr = sum(funding_rates) / len(funding_rates)
        if avg_fr <= -0.1 and not _cooldown(symbol, "funding_neg_extreme", 14400):
            send_alert(
                f"⚡ *{symbol} Extreme Negative Funding*\n"
                f"Avg: {avg_fr:+.4f}% — shorts dominant, squeeze risk\n"
                f"Price: ${price:,.2f}"
            )
            fired.append("funding_neg_extreme")
        elif avg_fr >= 0.15 and not _cooldown(symbol, "funding_pos_extreme", 14400):
            send_alert(
                f"⚡ *{symbol} Extreme Positive Funding*\n"
                f"Avg: {avg_fr:+.4f}% — longs over-extended, flush risk\n"
                f"Price: ${price:,.2f}"
            )
            fired.append("funding_pos_extreme")

    # ── Fear & Greed extremes (BTC/market-wide) ───────────────────────────────
    fg_score = fg.get("score")
    if fg_score is not None:
        if fg_score <= 10 and not _cooldown(symbol, "fear_extreme", 43200):
            send_alert(
                f"😱 *Extreme Fear* — F&G: {fg_score}/100\n"
                f"Historically a contrarian buy zone. {symbol}: ${price:,.2f}"
            )
            fired.append("fear_extreme")
        elif fg_score >= 90 and not _cooldown(symbol, "greed_extreme", 43200):
            send_alert(
                f"🤑 *Extreme Greed* — F&G: {fg_score}/100\n"
                f"Historically a contrarian sell zone. {symbol}: ${price:,.2f}"
            )
            fired.append("greed_extreme")

    # ── RSI divergence detected in conviction signals ─────────────────────────
    for sig in conviction["signals"]:
        if "divergence" in sig.lower():
            cond = "bull_divergence" if "bullish" in sig.lower() else "bear_divergence"
            if not _cooldown(symbol, cond, 14400):
                send_alert(
                    f"📐 *{symbol} RSI Divergence*\n"
                    f"{sig}\n"
                    f"Conviction: {cv_label} ({cv_score}/10)\n"
                    f"Price: ${price:,.2f}"
                )
                fired.append(cond)

    # ── High-conviction setup ─────────────────────────────────────────────────
    if cv_score >= 7.5 and not _cooldown(symbol, "high_conviction", 7200):
        top_sigs = "\n".join(f"  • {s}" for s in conviction["signals"][:5])
        send_alert(
            f"🔥 *High Conviction: {symbol}*\n"
            f"Score: {cv_score}/10 ({cv_label}) — {direction}\n"
            f"Horizon: {conviction['horizon'].capitalize()}\n"
            f"Price: ${price:,.2f}\n\n"
            f"Top signals:\n{top_sigs}"
        )
        fired.append("high_conviction")

    # ── Chain leader move — cascade watch ────────────────────────────────────
    from skills.chain_map import get_ecosystem
    if symbol in ("ETH", "SOL", "BNB", "AVAX"):
        price_chg = binance.get("change_24h_pct", 0)
        if abs(price_chg) >= 5 and not _cooldown(symbol, "chain_leader_move", 14400):
            eco = get_ecosystem(symbol) or symbol.lower()
            arrow = "📈" if price_chg > 0 else "📉"
            send_alert(
                f"{arrow} *{symbol} {price_chg:+.1f}%* — chain leader move\n"
                f"Watch {eco.capitalize()} alts for follow-through.\n"
                f"Price: ${price:,.2f}"
            )
            fired.append("chain_leader_move")

    # ── CEX/DEX arbitrage opportunity ────────────────────────────────────────
    dex_comp = data.get("dex_comparison", {})
    if dex_comp and dex_comp.get("dex_best"):
        arb_pct = dex_comp.get("arbitrage_pct", 0)
        dex_best = dex_comp["dex_best"]
        liquidity = dex_best.get("liquidity", 0)
        # Only alert on meaningful opportunities: 1%+ spread + sufficient liquidity to execute
        if abs(arb_pct) >= 1.0 and liquidity >= 500000 and not _cooldown(symbol, "dex_cex_arbitrage", 3600):
            direction = "SELL on DEX" if arb_pct > 0 else "BUY on DEX"
            arrow = "📊" if abs(arb_pct) < 2 else "🚀"
            send_alert(
                f"{arrow} *{symbol} CEX/DEX Arbitrage*\n"
                f"Spread: {arb_pct:+.2f}% — {direction}\n"
                f"CEX (Binance): ${price:,.2f}\n"
                f"DEX ({dex_best['dex']} on {dex_best['chain']}): ${dex_best['price']:,.2f}\n"
                f"Liquidity: ${liquidity:,.0f}"
            )
            fired.append("dex_cex_arbitrage")

    return fired


def scan_all() -> dict[str, dict]:
    """
    Fetch + cache + alert for all watched symbols. Returns {symbol: data}.
    Uses cached data when < _CACHE_TTL old; only hits TradingView on cache miss,
    with a sleep between fetches to avoid 429s.
    """
    from skills.watchlist import get_all_symbols
    results: dict[str, dict] = {}
    needs_fetch: list[str] = []
    cached_hits: list[str] = []

    for symbol in get_all_symbols():
        age = cache_age_seconds(symbol)
        if age is not None and age < _CACHE_TTL:
            cached_hits.append(symbol)
        else:
            needs_fetch.append(symbol)

    if cached_hits:
        print(f"[SCANNER] Using cache for: {', '.join(cached_hits)}")
    if needs_fetch:
        print(f"[SCANNER] Fetching fresh data for: {', '.join(needs_fetch)}")

    # Use cached data (no TV call)
    for symbol in cached_hits:
        data = get_cached(symbol)
        if data:
            results[symbol] = data

    # Fetch stale/missing assets one at a time with spacing
    for i, symbol in enumerate(needs_fetch):
        if i > 0:
            time.sleep(_FETCH_SLEEP)
        data = fetch_and_cache(symbol)
        if data:
            results[symbol] = data

    # Run alert checks on all results
    for symbol, data in results.items():
        alerts = check_alerts(symbol, data)
        if alerts:
            print(f"[SCANNER] {symbol}: fired {alerts}")

    return results
