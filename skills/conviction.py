"""
Multi-timeframe confluence and divergence scoring.
Produces a 0-10 conviction score for any asset's cached market data.
High score = multiple signals aligned in the same direction.
"""

import json
import redis as _redis_lib
from datetime import datetime, timezone

_r = _redis_lib.Redis(host="localhost", port=6379, db=0)

_PREV_KEY = "scanner:prev:{symbol}"
_CONV_KEY = "scanner:conviction:{symbol}"
_CONV_TTL = 900   # 15 min
_PREV_TTL = 3600  # 1h — keep prior state for divergence check


def _get_prev(symbol: str) -> dict:
    raw = _r.get(_PREV_KEY.format(symbol=symbol))
    return json.loads(raw) if raw else {}


def _save_prev(symbol: str, price: float, rsi: dict) -> None:
    _r.setex(
        _PREV_KEY.format(symbol=symbol),
        _PREV_TTL,
        json.dumps({"price": price, "rsi": rsi, "ts": datetime.now(timezone.utc).isoformat()}),
    )


def score(data: dict, symbol: str = "") -> dict:
    """
    Score market data against multi-TF confluence rules.
    Returns: {score, label, direction, signals, horizon, bull_pts, bear_pts, symbol, updated}
    """
    bull_pts = 0.0
    bear_pts = 0.0
    signals: list[str] = []

    binance = data.get("binance", {})
    ta      = data.get("ta", {})
    deriv   = data.get("derivatives", {})
    bybit   = data.get("bybit", {})
    okx     = data.get("okx", {})
    fg      = data.get("fear_greed", {})
    price   = binance.get("price", 0)
    rsi_map: dict[str, float] = {}

    # ── 1. RSI extremes per timeframe ─────────────────────────────────────────
    rsi_oversold_tfs: list[str]    = []
    rsi_overbought_tfs: list[str]  = []
    for tf in ("1h", "4h", "1d"):
        ta_tf = ta.get(tf, {})
        rsi   = ta_tf.get("rsi")
        if rsi is None:
            continue
        rsi_map[tf] = rsi
        if rsi <= 20:
            bull_pts += 2.0
            rsi_oversold_tfs.append(tf)
            signals.append(f"RSI {rsi:.0f} ({tf}) — extreme oversold")
        elif rsi <= 30:
            bull_pts += 1.0
            rsi_oversold_tfs.append(tf)
            signals.append(f"RSI {rsi:.0f} ({tf}) — oversold")
        elif rsi >= 80:
            bear_pts += 2.0
            rsi_overbought_tfs.append(tf)
            signals.append(f"RSI {rsi:.0f} ({tf}) — extreme overbought")
        elif rsi >= 70:
            bear_pts += 1.0
            rsi_overbought_tfs.append(tf)
            signals.append(f"RSI {rsi:.0f} ({tf}) — overbought")

    # Multi-TF RSI confluence bonus (the key high-conviction signal)
    if len(rsi_oversold_tfs) >= 2:
        bull_pts += 2.5
        signals.append(f"RSI oversold on {len(rsi_oversold_tfs)} TFs: {', '.join(rsi_oversold_tfs)} — high confluence")
    if len(rsi_overbought_tfs) >= 2:
        bear_pts += 2.5
        signals.append(f"RSI overbought on {len(rsi_overbought_tfs)} TFs: {', '.join(rsi_overbought_tfs)} — high confluence")

    # ── 2. RSI divergence (compare vs previous cached snapshot) ───────────────
    prev       = _get_prev(symbol) if symbol else {}
    prev_price = prev.get("price", 0)
    prev_rsi   = prev.get("rsi", {})
    if price and prev_price and rsi_map:
        for tf in ("4h", "1d"):
            rsi_now  = rsi_map.get(tf)
            rsi_then = prev_rsi.get(tf)
            if rsi_now is None or rsi_then is None:
                continue
            price_fell = price < prev_price * 0.995  # >0.5% move to count
            price_rose = price > prev_price * 1.005
            rsi_rose   = rsi_now > rsi_then + 1
            rsi_fell   = rsi_now < rsi_then - 1
            if price_fell and rsi_rose:
                bull_pts += 2.0
                signals.append(f"Bullish RSI divergence ({tf}): price lower, RSI higher")
            elif price_rose and rsi_fell:
                bear_pts += 2.0
                signals.append(f"Bearish RSI divergence ({tf}): price higher, RSI lower")

    if symbol and price and rsi_map:
        _save_prev(symbol, price, rsi_map)

    # ── 3. MACD alignment ─────────────────────────────────────────────────────
    for tf in ("4h", "1d"):
        ta_tf    = ta.get(tf, {})
        macd     = ta_tf.get("macd")
        mac_sig  = ta_tf.get("macd_signal")
        if macd is None or mac_sig is None:
            continue
        if macd > mac_sig:
            bull_pts += 0.5
            signals.append(f"MACD above signal ({tf})")
        else:
            bear_pts += 0.5
            signals.append(f"MACD below signal ({tf})")

    # ── 4. EMA structure ──────────────────────────────────────────────────────
    ta_1d  = ta.get("1d", {})
    ema20  = ta_1d.get("ema_20")
    ema50  = ta_1d.get("ema_50")
    ema200 = ta_1d.get("ema_200")
    if price and ema20 and ema50 and ema200:
        if price > ema20 > ema50 > ema200:
            bull_pts += 2.0
            signals.append("Full EMA bull stack (price > EMA20 > 50 > 200)")
        elif price < ema20 < ema50 < ema200:
            bear_pts += 2.0
            signals.append("Full EMA bear stack (price < EMA20 < 50 < 200)")
        else:
            if price > ema200:
                bull_pts += 0.5
            elif price < ema200:
                bear_pts += 0.5

    # ── 5. ADX trend strength amplifier ───────────────────────────────────────
    adx_1d = ta_1d.get("adx")
    if adx_1d:
        amp = 1.0 if adx_1d > 40 else 0.5 if adx_1d > 25 else 0
        if amp:
            if bull_pts > bear_pts:
                bull_pts += amp
                signals.append(f"ADX {adx_1d:.0f} — strong trend confirms bull direction")
            elif bear_pts > bull_pts:
                bear_pts += amp
                signals.append(f"ADX {adx_1d:.0f} — strong trend confirms bear direction")

    # ── 6. Bollinger Bands ────────────────────────────────────────────────────
    for tf in ("4h", "1d"):
        ta_tf = ta.get(tf, {})
        bb_u  = ta_tf.get("bb_upper")
        bb_l  = ta_tf.get("bb_lower")
        bb_b  = ta_tf.get("bb_basis")
        if not (bb_u and bb_l and price):
            continue
        if price <= bb_l:
            bull_pts += 1.0
            signals.append(f"Price at/below BB lower band ({tf}) — oversold")
        elif price >= bb_u:
            bear_pts += 1.0
            signals.append(f"Price at/above BB upper band ({tf}) — overbought")
        if bb_b and (bb_u - bb_l) / bb_b < 0.02:
            signals.append(f"BB squeeze ({tf}) — breakout pending")

    # ── 7. Funding rate (contrarian signal) ───────────────────────────────────
    funding_rates: list[float] = []
    for src in (deriv, bybit, okx):
        fr = src.get("funding_rate_pct")
        if fr is not None:
            funding_rates.append(fr)
    if funding_rates:
        avg_fr = sum(funding_rates) / len(funding_rates)
        if avg_fr <= -0.1:
            bull_pts += 2.0
            signals.append(f"Extreme negative funding {avg_fr:+.4f}% — shorts dominant, contrarian bullish")
        elif avg_fr <= -0.05:
            bull_pts += 1.0
            signals.append(f"Negative funding {avg_fr:+.4f}% — contrarian bullish")
        elif avg_fr >= 0.1:
            bear_pts += 2.0
            signals.append(f"Extreme positive funding {avg_fr:+.4f}% — longs over-extended, contrarian bearish")
        elif avg_fr >= 0.05:
            bear_pts += 1.0
            signals.append(f"Positive funding {avg_fr:+.4f}% — contrarian bearish")

    # ── 8. OI + price direction alignment ────────────────────────────────────
    oi_chg    = deriv.get("oi_change_24h_pct")
    price_chg = binance.get("change_24h_pct")
    if oi_chg is not None and price_chg is not None:
        if oi_chg > 5 and price_chg > 1:
            bull_pts += 1.0
            signals.append(f"OI +{oi_chg:.1f}% with price +{price_chg:.1f}% — bullish continuation")
        elif oi_chg > 5 and price_chg < -1:
            bear_pts += 1.0
            signals.append(f"OI +{oi_chg:.1f}% with price {price_chg:.1f}% — bearish continuation")
        elif oi_chg < -5:
            signals.append(f"OI {oi_chg:.1f}% — deleveraging, potential reversal setup")

    # ── 9. Fear & Greed (contrarian) ─────────────────────────────────────────
    fg_score = fg.get("score")
    if fg_score is not None:
        if fg_score <= 10:
            bull_pts += 2.0
            signals.append(f"F&G {fg_score}/100 — extreme fear, contrarian bullish")
        elif fg_score <= 20:
            bull_pts += 1.0
            signals.append(f"F&G {fg_score}/100 — fear zone, contrarian bullish")
        elif fg_score >= 90:
            bear_pts += 2.0
            signals.append(f"F&G {fg_score}/100 — extreme greed, contrarian bearish")
        elif fg_score >= 80:
            bear_pts += 1.0
            signals.append(f"F&G {fg_score}/100 — greed zone, contrarian bearish")

    # ── 10. Volume spike ──────────────────────────────────────────────────────
    vol_chg = binance.get("volume_change_pct")
    if vol_chg is not None and abs(vol_chg) >= 50:
        dominant = "bull" if bull_pts >= bear_pts else "bear"
        signals.append(f"Volume spike {vol_chg:+.0f}% vs prior day — confirms {dominant} move")
        if bull_pts >= bear_pts:
            bull_pts += 1.0
        else:
            bear_pts += 1.0

    # ── Final scoring ─────────────────────────────────────────────────────────
    dominant_pts = max(bull_pts, bear_pts)
    total_pool   = bull_pts + bear_pts or 1.0
    direction    = "bullish" if bull_pts >= bear_pts else "bearish"
    dominance    = dominant_pts / total_pool

    # Normalize raw score to 0-10 (cap at 15 raw points)
    score_10 = round(min(dominant_pts, 15) / 15 * 10, 1)

    # Penalize mixed signals (neither side clearly dominant)
    if dominance < 0.60:
        score_10 = round(score_10 * 0.65, 1)

    label = (
        "Very High" if score_10 >= 8.0 else
        "High"      if score_10 >= 6.0 else
        "Medium"    if score_10 >= 3.5 else
        "Low"
    )

    # Recommended horizon from which TFs are most active
    active_tfs = set(rsi_oversold_tfs + rsi_overbought_tfs)
    horizon = (
        "scalp"    if "1h" in active_tfs and not ("4h" in active_tfs or "1d" in active_tfs) else
        "day"      if "4h" in active_tfs and "1d" not in active_tfs else
        "swing"
    )

    result = {
        "score":     score_10,
        "label":     label,
        "direction": direction,
        "signals":   signals,
        "horizon":   horizon,
        "bull_pts":  round(bull_pts, 1),
        "bear_pts":  round(bear_pts, 1),
        "symbol":    symbol,
        "updated":   datetime.now(timezone.utc).isoformat(),
    }

    if symbol:
        _r.setex(_CONV_KEY.format(symbol=symbol), _CONV_TTL, json.dumps(result))

    return result


def get_cached(symbol: str) -> dict | None:
    raw = _r.get(_CONV_KEY.format(symbol=symbol))
    return json.loads(raw) if raw else None


def format_conviction(c: dict, symbol: str = "") -> str:
    sym   = symbol or c.get("symbol", "?")
    icon  = "🔥" if c["score"] >= 8 else "⚡" if c["score"] >= 6 else "📊"
    lines = [
        f"{icon} *{sym} Conviction: {c['label']} ({c['score']}/10)*",
        f"Direction: {c['direction'].capitalize()}  |  Horizon: {c['horizon'].capitalize()}",
        "",
        "*Signals:*",
    ]
    for s in c["signals"]:
        lines.append(f"  • {s}")
    if not c["signals"]:
        lines.append("  (no strong signals detected)")
    return "\n".join(lines)
