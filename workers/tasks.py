import os
import sys
import time
import redis
import requests
from dotenv import load_dotenv

sys.path.insert(0, '/root/bastobot')

load_dotenv('/root/bastobot/.env')
OR_KEY = os.getenv("OPENROUTER_API_KEY")

_redis = redis.Redis(host='localhost', port=6379, db=0)
_TIMING_WINDOW = 10  # rolling average over last N jobs


def record_timing(category, elapsed):
    key = f"timing:{category}"
    pipe = _redis.pipeline()
    pipe.lpush(key, round(elapsed, 1))
    pipe.ltrim(key, 0, _TIMING_WINDOW - 1)
    pipe.execute()


def get_avg_timing(category):
    times = _redis.lrange(f"timing:{category}", 0, -1)
    if not times:
        return None
    return sum(float(t) for t in times) / len(times)

TRADING_INSTRUCTION = """You are a sharp, no-fluff crypto derivatives analyst. Use all live market data provided.

BIAS RULE: Do NOT default to bullish. Determine direction from the data:
- Downtrend (lower highs/lows, price below EMAs, negative funding) → SHORT or RANGE bias
- Uptrend → LONG bias
- Choppy/ranging → RANGE bias with limit orders at extremes
Oversold RSI alone does NOT justify a long if the trend is bearish.

TRADE LOGIC: SHORT entry must be ABOVE TP1 which must be ABOVE TP2 — you sell high, buy back lower.
LONG entry must be BELOW TP1 which must be BELOW TP2 — you buy low, sell higher.
Never present a setup where entry and TP are on the wrong side of each other.

For snapshot / market overview requests, respond in exactly this format (no extra sections, no disclaimers):

BTC Snapshot — [Month DD, YYYY]

Price: $[price] ([+/-X.XX%] 24h, [+/-X.XX%] 7d). [One sentence on macro context.]

Key levels:
- Resistance: $[level] ([reason]), $[level] ([reason])
- Support: $[level] ([reason]), $[level] ([reason])

Trend:
- 1h: [brief read — range, direction, volume context]
- 4h: [brief read]
- 1d: [brief read — higher highs/lows, key EMA relationships]

Indicators:
- RSI [value] — [label: neutral/overbought/oversold]
- Volume $[XB], [+/-X%] — [one-word conviction label]
- Bollinger [position relative to bands] — [compression/expansion note]

Derivatives:
- Funding: [exchanges + rates] — [interpretation]
- OI $[XB] ([+/-X%]) — [label]
- Liquidations $[XM] ([+/-X%]) — [label]
- L/S ratio: [global]/[top traders] — [interpretation]
- Fear & Greed: [score] ([label] — [contrarian note if relevant])

Bias: [Long / Short / Range] — [one line: what confirms it]
- Continuation: [trigger] → [target]
- Invalidation: [level that flips the bias]

Trade Setup: [LONG / SHORT / RANGE]
[For directional — single or scaled entry:]
- Direction: Long / Short
- Entry: $[price] OR $[X] / $[Y] / $[Z] (3 equal lots, avg $[avg])
- SL: $[level] ([invalidation reason])
- TP1: $[level] ([nearest measured move])
- TP2: $[level] ([extended target])

[For range — limit orders stacked TIGHTLY at each extreme:]
- Range: $[support] – $[resistance]
- Buy limit: $[support] / $[support - 0.3%] / $[support - 0.6%] (3 equal lots, avg ~$[avg], clustered at support)
- Sell limit: $[resistance] / $[resistance + 0.3%] / $[resistance + 0.6%] (3 equal lots, avg ~$[avg], clustered at resistance)
- SL long: $[below support - 1%], SL short: $[above resistance + 1%]
- TP long: $[near resistance], TP short: $[near support]
NOTE: Entries must be stacked within ~0.5–1% of the key level, NOT spread across the full range width.

For trade setup requests, lead with direction then Entry, SL, TP1, TP2 — supported by the most relevant data.

For simple price questions, give a direct 2-3 line answer. Always lead with the conclusion. No filler."""

_KNOWN_ASSETS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "DOT", "LINK",
    "MATIC", "UNI", "ATOM", "LTC", "BCH", "NEAR", "APT", "SUI", "OP", "ARB",
    "INJ", "TIA", "PEPE", "WIF", "BONK", "TON", "SHIB", "TRX", "HBAR",
]
_ASSET_NAME_MAP = {
    "BITCOIN": "BTC", "ETHEREUM": "ETH", "SOLANA": "SOL", "BINANCE": "BNB",
    "RIPPLE": "XRP", "DOGECOIN": "DOGE", "CARDANO": "ADA", "AVALANCHE": "AVAX",
    "POLKADOT": "DOT", "CHAINLINK": "LINK", "POLYGON": "MATIC", "UNISWAP": "UNI",
    "COSMOS": "ATOM", "LITECOIN": "LTC", "TONCOIN": "TON", "TRON": "TRX",
    "SHIBA": "SHIB",
}

def _detect_asset(prompt: str) -> str:
    if not prompt:
        return "BTC"
    upper = prompt.upper()
    # Check full-word ticker matches first (longest first to avoid BNB matching inside BONK etc.)
    words = set(upper.split())
    for asset in sorted(_KNOWN_ASSETS, key=len, reverse=True):
        if asset in words:
            return asset
    # Substring match as fallback
    for name, ticker in _ASSET_NAME_MAP.items():
        if name in upper:
            return ticker
    return "BTC"


_HORIZON_SCALP    = "scalp"
_HORIZON_DAY      = "day"
_HORIZON_SWING    = "swing"
_HORIZON_POSITION = "position"

_HORIZON_KEYWORDS = {
    _HORIZON_SCALP:    ("scalp", "quick trade", "quick entry"),
    _HORIZON_DAY:      ("day trade", "daytrade", "intraday", "day-trade"),
    _HORIZON_POSITION: ("position trade", "long term", "weekly trade", "macro trade"),
}

def _detect_trade_horizon(prompt: str) -> str:
    if not prompt:
        return _HORIZON_SWING
    p = prompt.lower()
    for horizon, keywords in _HORIZON_KEYWORDS.items():
        if any(kw in p for kw in keywords):
            return horizon
    return _HORIZON_SWING

_HORIZON_META = {
    _HORIZON_SCALP: {
        "label":    "SCALP",
        "duration": "15min–2h",
        "focus":    "1h RSI extremes, recent liquidation clusters, micro-structure momentum",
        "valid":    "2–4h — reassess on any 1h close outside entry zone",
        "candles":  ("5m", "15m", "1h"),
        "lookback": "24h",
    },
    _HORIZON_DAY: {
        "label":    "DAY TRADE",
        "duration": "2h–24h",
        "focus":    "4h trend direction, 1h entry trigger, intraday key levels",
        "valid":    "12–24h — reassess on 4h close against the position",
        "candles":  ("30m", "1h", "4h"),
        "lookback": "7d",
    },
    _HORIZON_SWING: {
        "label":    "SWING",
        "duration": "2–7 days",
        "focus":    "1D trend structure, weekly key levels, funding rate trend, OI direction",
        "valid":    "24–72h — reassess on 1D close outside key structure",
        "candles":  ("4h", "1d"),
        "lookback": "30d",
    },
    _HORIZON_POSITION: {
        "label":    "POSITION",
        "duration": "1–4 weeks",
        "focus":    "1W trend, macro regime, sustained funding anomaly, major structural levels",
        "valid":    "weekly — reassess on weekly close against key level",
        "candles":  ("1d", "1w"),
        "lookback": "90d",
    },
}

def build_snapshot_instruction(horizon: str, asset: str = "BTC", open_trade: dict | None = None) -> str:
    meta = _HORIZON_META.get(horizon, _HORIZON_META[_HORIZON_SWING])
    a = asset
    candles = meta["candles"]
    lookback = meta["lookback"]
    trend_lines = "\n".join(f"- {c}: [brief read]" for c in candles)

    if open_trade:
        t = open_trade
        tp2_line = f"\n  TP2:       ${t['tp2']:,.2f}" if t.get("tp2") else ""
        trade_context = (
            f"\nOPEN TRADE (real, tracked by the system — reference this in Prior Trade Update):\n"
            f"  Symbol:    {t['symbol']}\n"
            f"  Direction: {t['direction']}\n"
            f"  Horizon:   {t['horizon'].capitalize()}\n"
            f"  Entry:     ${t['entry']:,.2f}\n"
            f"  SL:        ${t['sl']:,.2f}\n"
            f"  TP1:       ${t['tp1']:,.2f}{tp2_line}\n"
            f"  Entered:   {t['entered_at'][:10]}\n\n"
            f"Include a '--- Prior Trade Update ---' section at the end: is the trade still valid? "
            f"Has price moved toward TP or SL? Should the SL be trailed? State clearly: Hold / Adjust SL / Close.\n"
        )
    else:
        trade_context = (
            "\nNo open trades for this asset. "
            "Do NOT include a 'Prior Trade Update' section — you have no memory of previous setups.\n"
        )

    return f"""You are a sharp, no-fluff crypto derivatives analyst. Use all live market data provided.
Data covers the last {lookback}. Focus analysis on the {'/'.join(c.upper() for c in candles)} timeframes.
CRITICAL: The PRIMARY SETUP section label MUST be exactly "{meta['label']}" — do not substitute any other trade type label.
{trade_context}
BIAS RULE — MUST FOLLOW:
- Do NOT default to bullish. Derive direction from the data.
- Downtrend (lower highs/lows, price below key EMAs, negative funding, bearish structure) → PRIMARY SETUP = SHORT or RANGE
- Uptrend (higher highs/lows, price above key EMAs, positive structure) → PRIMARY SETUP = LONG
- Choppy / sideways → PRIMARY SETUP = RANGE with limit orders at both extremes
- Oversold RSI alone is NOT a reason to go long if trend is bearish — state RANGE or SHORT first

TRADE LOGIC RULES — NEVER VIOLATE:
- SHORT: Entry MUST be ABOVE TP1 MUST be ABOVE TP2. You sell at entry, buy back lower. Entry < TP1 is nonsense.
- LONG: Entry MUST be BELOW TP1 MUST be BELOW TP2. You buy at entry, sell higher. Entry > TP1 is nonsense.
- BONUS SETUP: Its entry must be at a price level clearly distinct from the primary setup's TP levels.
  If the bonus entry is near the primary's TP1, it is a ROLL/CONTINUATION trade — label it as such and explain it explicitly.
  Do NOT present a bonus setup whose entry overlaps with the primary setup's exit zone without explaining the relationship.

ENTRY FORMAT:
- Single entry: $[price]
- Scaled/laddered: $[X] / $[Y] / $[Z] (3 equal lots, avg $[avg])  — use when entry zone is wide or conviction is medium

RANGE SETUP FORMAT (use when market is choppy/ranging):
Entries stack TIGHTLY at the key level — within 0.5–1% of the level, NOT spread across the full range.
- Buy limit: $[support] / $[support - 0.3%] / $[support - 0.6%] (3 equal lots, avg clustered at support)
- Sell limit: $[resistance] / $[resistance + 0.3%] / $[resistance + 0.6%] (3 equal lots, avg clustered at resistance)
- SL long: $[below support - 1%], SL short: $[above resistance + 1%]
- TP long: $[near resistance], TP short: $[near support]

Respond in exactly this format (no extra sections, no disclaimers):

{a} Snapshot — [Month DD, YYYY]

Price: $[price] ([+/-X.XX%] 24h, [+/-X.XX%] 7d). [One sentence on macro context.]

Key levels:
- Resistance: $[level] ([reason]), $[level] ([reason])
- Support: $[level] ([reason]), $[level] ([reason])

Trend:
{trend_lines}

Indicators:
- RSI [value] — [label: neutral/overbought/oversold]
- Volume $[XB], [+/-X%] — [one-word conviction label]
- Bollinger [position relative to bands] — [compression/expansion note]

Derivatives:
- Funding: [exchanges + rates] — [interpretation]
- OI $[XB] ([+/-X%]) — [label]
- Liquidations $[XM] ([+/-X%]) — [label]
- L/S ratio: [global]/[top traders] — [interpretation]
- Fear & Greed: [score] ([label] — [contrarian note if relevant])

Bias: [Long / Short / Range] — [one line: structural reason]
- Continuation: [trigger] → [target]
- Invalidation: [level that flips the bias]

━━━ PRIMARY SETUP — {meta['label']} ━━━
Horizon:    {meta['duration']}
Valid for:  {meta['valid']}
Direction:  [LONG / SHORT / RANGE]

[If LONG or SHORT:]
Entry:       $[price] OR $[X] / $[Y] / $[Z] (3 equal lots, avg $[avg])
SL:          $[level] ([invalidation reason])
TP1:         $[level] ([nearest measured move]) → on hit: move SL to $[near-entry buffer]
TP2:         $[level] ([extended target])
R:R:         [X:X to TP1] / [X:X to TP2]

[If RANGE — stack entries tightly AT the key level, NOT spread across the range:]
Range:       $[support] – $[resistance]
Buy limit:   $[support] / $[support - 0.3%] / $[support - 0.6%] (3 equal lots, avg clustered at support)
Sell limit:  $[resistance] / $[resistance + 0.3%] / $[resistance + 0.6%] (3 equal lots, avg clustered at resistance)
SL long:     $[below support - 1%]
SL short:    $[above resistance + 1%]
TP long:     $[near resistance], TP short: $[near support]

Conviction:  [High / Medium / Low] — [one-line: which signals align]

[Only include if a materially stronger setup exists at a different timeframe. Omit entirely if nothing stands out.]
⭐ BONUS HIGH-CONVICTION SETUP — [SWING / POSITION / DAY / SCALP]
Direction: [LONG / SHORT / RANGE]
Entry:  $[zone] OR $[X] / $[Y] / $[Z] (3 equal lots)
SL:     $[level]
TP1:    $[level] → move SL to $[near-entry]
TP2:    $[level]
R:R:    [X:X to TP1] / [X:X to TP2]
Why:    [2–3 signals: timeframe alignment, derivatives confirmation, structure]

For simple price questions, give a direct 2-3 line answer. Always lead with the conclusion. No filler."""


def _fetch_market_data(asset="BTC", candles=None, data=None):
    try:
        if data is None:
            # Use scanner cache when available (< 10 min old) to avoid redundant API calls
            try:
                from skills.scanner import get_cached
                data = get_cached(asset)
                if data is not None:
                    print(f"[CACHE] Using cached data for {asset}")
            except Exception:
                pass
        if data is None:
            from skills.trading import get_btc_analysis, get_asset_analysis
            if asset == "BTC":
                data = get_btc_analysis(candles=candles)
            else:
                data = get_asset_analysis(asset, candles=candles)
        d = data
        if not isinstance(d, dict):
            return None

        from datetime import datetime
        lines = [f"[LIVE MARKET DATA — {asset}/USDT — {datetime.utcnow().strftime('%b %d, %Y %H:%M UTC')}]"]

        # --- Price ---
        if "binance" in d:
            b = d["binance"]
            vol_chg = f"{b['volume_change_pct']:+.1f}%" if "volume_change_pct" in b else "N/A"
            lines.append(
                f"Price: ${b['price']:,.2f}  "
                f"24h: {b['change_24h_pct']:+.2f}%  "
                f"7d: {b['change_7d_pct']:+.2f}%  "
                f"H/L 24h: ${b['high_24h']:,.0f}/${b['low_24h']:,.0f}"
            )
            lines.append(
                f"Volume (yesterday): ${b['volume_yesterday_usdt']/1e9:.2f}B  "
                f"Change vs prior day: {vol_chg}"
            )

        # --- Multi-timeframe TA (iterate actual keys — respects horizon candles) ---
        if "ta" in d:
            for tf in d["ta"]:
                ta = d["ta"][tf]
                sig = ta["summary"].get("RECOMMENDATION", "N/A")
                bb = ""
                if ta.get("bb_upper") and ta.get("bb_lower"):
                    bb = f"  BB: ${ta['bb_lower']:,.0f}–${ta['bb_upper']:,.0f} (mid ${ta['bb_basis']:,.0f})"
                lines.append(
                    f"[{tf.upper()}] Signal: {sig}  RSI: {ta['rsi']}  ADX: {ta['adx']}  "
                    f"EMA20/50/200: ${ta['ema_20']:,.0f}/${ta['ema_50']:,.0f}/${ta['ema_200']:,.0f}"
                    f"{bb}"
                )

        # --- Market context ---
        if "market" in d:
            m = d["market"]
            lines.append(
                f"BTC Dominance: {m['btc_dominance_pct']}%  "
                f"Total Crypto MCap: ${m['total_market_cap_usd']/1e12:.2f}T  "
                f"Total 24h Volume: ${m['total_volume_24h_usd']/1e9:.1f}B"
            )

        # --- Cross-exchange OI ---
        oi_parts = []
        oi_totals = []
        if "derivatives" in d:
            v = d["derivatives"].get("oi_usd_bn", 0)
            oi_parts.append(f"Binance ${v}B")
            oi_totals.append(v)
        if "bybit" in d:
            v = d["bybit"]["oi_usd_bn"]
            oi_parts.append(f"Bybit ${v}B")
            oi_totals.append(v)
        if "okx" in d:
            v = d["okx"]["oi_usd_bn"]
            oi_parts.append(f"OKX ${v}B")
            oi_totals.append(v)
        if oi_totals:
            oi_chg = ""
            if "derivatives" in d:
                oi_chg = f" ({d['derivatives']['oi_change_24h_pct']:+.2f}% 24h)"
            lines.append(
                f"Open Interest: {' | '.join(oi_parts)} = ~${round(sum(oi_totals), 2)}B total{oi_chg}"
            )

        # --- Binance Futures derivatives ---
        if "derivatives" in d:
            dv = d["derivatives"]
            funding_line = (
                f"Binance Funding: {dv['funding_rate_pct']:+.4f}%  "
                f"Mark: ${dv['mark_price']:,.2f}"
            )
            if "premium_pct" in dv:
                funding_line += f"  Premium: {dv['premium_pct']:+.4f}%"
            lines.append(funding_line)
            if "global_ls_ratio" in dv:
                ls_line = (
                    f"Global L/S: {dv['global_ls_ratio']:.3f} "
                    f"({dv['global_longs_pct']}% long / {dv['global_shorts_pct']}% short)"
                )
                if "top_trader_ls_ratio" in dv:
                    ls_line += (
                        f"  Top Traders: {dv['top_trader_ls_ratio']:.3f} "
                        f"({dv['top_trader_longs_pct']}% long / {dv['top_trader_shorts_pct']}% short)"
                    )
                lines.append(ls_line)
            if "taker_buy_sell_ratio" in dv:
                lines.append(f"Taker Buy/Sell: {dv['taker_buy_sell_ratio']:.4f}")

        # --- Bybit + OKX funding/L/S ---
        if "bybit" in d:
            by = d["bybit"]
            lines.append(
                f"Bybit Funding: {by['funding_rate_pct']:+.4f}%  "
                f"L/S: {by['longs_pct']}% long / {by['shorts_pct']}% short"
            )
        if "okx" in d:
            ok = d["okx"]
            lines.append(
                f"OKX Funding: {ok['funding_rate_pct']:+.4f}%  "
                f"L/S: {ok['longs_pct']}% long / {ok['shorts_pct']}% short"
            )

        # --- Liquidations ---
        if "liquidations" in d:
            lq = d["liquidations"]
            total = lq["total_liq_usd"]
            chg = f" ({lq['change_pct']:+.1f}% vs prior 24h)" if lq.get("change_pct") is not None else ""
            lines.append(
                f"Liquidations 24h: Longs ${lq['longs_liq_usd']:,} | "
                f"Shorts ${lq['shorts_liq_usd']:,} | Total ${total:,}{chg}"
            )
            if lq["top_liq_zones"]:
                lines.append(f"  Top liq zones: {' | '.join(lq['top_liq_zones'])}")

        # --- Fear & Greed ---
        if "fear_greed" in d:
            fg = d["fear_greed"]
            lines.append(f"Fear & Greed: {fg['score']}/100 — {fg['label']}")

        # --- Polymarket ---
        if "polymarket" in d and d["polymarket"]:
            lines.append("Polymarket BTC markets:")
            for pm in d["polymarket"]:
                lines.append(f"  {round(pm['yes_prob']*100,1)}% Yes — {pm['question']}")

        # --- Coinglass (if unlocked) ---
        if "coinglass" in d and d["coinglass"]:
            cg = d["coinglass"]
            parts = [f"{k}: {v}" for k, v in cg.items()]
            lines.append("Coinglass: " + " | ".join(parts))

        # --- SoSo Value ETF flows (if unlocked) ---
        if "sosovalue" in d and d["sosovalue"]:
            lines.append(f"SoSo Value ETF Flows: {d['sosovalue']}")

        return "\n".join(lines)
    except Exception as e:
        print(f"Market data fetch failed: {e}")
    return None

def _build_content(prompt, category, image_b64, mime_type):
    if image_b64:
        instruction = TRADING_INSTRUCTION if category in ('financial', 'vision') else ""
        text = f"{instruction}\n\n{prompt}".strip() if instruction else (prompt or "Analyse this chart.")
        return [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}}
        ]
    if category == 'financial':
        asset = _detect_asset(prompt)
        instruction = TRADING_INSTRUCTION.replace("BTC", asset)
        market = _fetch_market_data(asset)
        base = f"{instruction}\n\n{prompt}".strip()
        return f"{base}\n\n{market}" if market else base
    if category == 'vision':
        return f"{TRADING_INSTRUCTION}\n\n{prompt}".strip()
    # For all other text queries, inject current time so the model knows "now"
    try:
        from skills.time import get_time_context
        time_ctx = get_time_context()
        return f"{time_ctx}\n\n{prompt}" if prompt else prompt
    except Exception:
        pass
    return prompt

TEXT_MODELS = [
    "google/gemini-2.0-flash-001",
    "deepseek/deepseek-r1",
    "meta-llama/llama-3.3-70b-instruct",
]
VISION_MODELS = [
    "google/gemini-2.0-flash-001",
    "anthropic/claude-3-haiku",
]

def _call_model(models, content):
    payload = {
        "models": models,
        "messages": [{"role": "user", "content": content}],
        "route": "fallback",
    }
    response = requests.post(
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OR_KEY}"},
        json=payload,
        timeout=90,
    )
    data = response.json()
    if 'choices' not in data:
        raise RuntimeError(data.get('error', {}).get('message', str(data)))
    return data['choices'][0]['message']['content']

_SNAPSHOT_KEYWORDS = (
    "snapshot", "market overview", "market update", "market check",
    "scalp", "day trade", "daytrade", "intraday",
    "swing trade", "swing setup",
    "position trade", "trade idea", "trade setup",
)

def _is_snapshot_request(prompt: str) -> bool:
    if not prompt:
        return False
    p = prompt.lower().strip()
    return any(kw in p for kw in _SNAPSHOT_KEYWORDS)


import re as _re

def _handle_scanner_command(prompt: str) -> str | None:
    """
    Intercepts scanner/watchlist/trade commands before the LLM pipeline.
    Returns a response string if matched, None to fall through to normal processing.
    """
    if not prompt:
        return None
    p = prompt.strip()
    pl = p.lower()

    # ── Watchlist ─────────────────────────────────────────────────────────────
    # "watch SOL" or "watch SOL - solana L1 narrative"
    m = _re.match(r'^watch\s+([A-Za-z0-9]+)(?:\s*[-:]\s*(.+))?$', p, _re.IGNORECASE)
    if m:
        from skills.watchlist import add_user
        ok, msg = add_user(m.group(1), (m.group(2) or "").strip())
        return msg

    m = _re.match(r'^(unwatch|remove from watchlist|remove)\s+([A-Za-z0-9]+)$', pl)
    if m:
        from skills.watchlist import remove_user
        ok, msg = remove_user(m.group(2).upper())
        return msg

    if pl in ("watchlist", "my watchlist", "show watchlist", "wl"):
        from skills.watchlist import format_watchlist
        return format_watchlist()

    # ── Hot trades ────────────────────────────────────────────────────────────
    if any(pl.startswith(kw) for kw in ("hot trades", "top trades", "top setups", "hot setups", "best setups")):
        from skills.hot_trades import format_hot_trades
        return format_hot_trades()

    # ── Open trades ───────────────────────────────────────────────────────────
    if pl in ("my trades", "open trades", "trades", "show trades", "positions"):
        from skills.trade_monitor import format_open_trades
        return format_open_trades()

    # "close trade ETH" / "close ETH trade" / "close ETH"
    m = _re.match(r'^close(?:\s+trade)?\s+([A-Za-z0-9]+)$', pl)
    if not m:
        m = _re.match(r'^close\s+([A-Za-z0-9]+)\s+trade$', pl)
    if m:
        from skills.trade_monitor import close_trade
        ok, msg = close_trade(m.group(1).upper())
        return msg

    # ── Conviction score ──────────────────────────────────────────────────────
    m = _re.match(r'^(conviction|score|cv|signals)\s+([A-Za-z0-9]+)$', pl)
    if m:
        sym = m.group(2).upper()
        from skills.scanner import get_or_fetch
        from skills.conviction import score as conv_score, format_conviction
        data = get_or_fetch(sym)
        if not data:
            return f"Could not fetch data for {sym}."
        cv = conv_score(data, sym)
        return format_conviction(cv, sym)

    # ── Manual scan ───────────────────────────────────────────────────────────
    if pl in ("scan", "scan now", "run scan", "rescan"):
        from scripts.scanner_service import run_scan
        run_scan()
        from skills.hot_trades import format_hot_trades
        return "Scan complete.\n\n" + format_hot_trades()

    # ── Trade entry ───────────────────────────────────────────────────────────
    # "trade ETH long 3200 sl 3100 tp1 3400 tp2 3600 swing"
    # "monitor BTC short 95000 sl 96500 tp1 91000 day"
    m = _re.match(
        r'^(?:trade|monitor|enter trade|enter)\s+'
        r'([A-Za-z0-9]+)\s+'
        r'(long|short)\s+'
        r'([\d,]+(?:\.\d+)?)\s+'
        r'sl\s+([\d,]+(?:\.\d+)?)\s+'
        r'tp1?\s+([\d,]+(?:\.\d+)?)'
        r'(?:\s+tp2\s+([\d,]+(?:\.\d+)?))?'
        r'(?:\s+(scalp|day|swing|position))?',
        pl, _re.IGNORECASE
    )
    if m:
        from skills.trade_monitor import enter_trade
        sym       = m.group(1).upper()
        direction = m.group(2).capitalize()
        entry     = float(m.group(3).replace(",", ""))
        sl        = float(m.group(4).replace(",", ""))
        tp1       = float(m.group(5).replace(",", ""))
        tp2       = float(m.group(6).replace(",", "")) if m.group(6) else None
        horizon   = (m.group(7) or "swing").lower()
        # Grab conviction label from cache if available
        conviction_label = None
        try:
            from skills.conviction import get_cached as conv_cached
            cv = conv_cached(sym)
            if cv:
                conviction_label = cv["label"]
        except Exception:
            pass
        trade = enter_trade(sym, direction, entry, sl, tp1, tp2, horizon, conviction=conviction_label)
        notion_note = f"\n📓 Logged: {trade['notion_url']}" if trade.get("notion_url") else ""
        tp2_str = f"  TP2: ${tp2:,.2f}" if tp2 else ""
        return (
            f"✅ *Trade entered: {sym} {direction}*\n"
            f"Entry: ${entry:,.2f}  SL: ${sl:,.2f}\n"
            f"TP1: ${tp1:,.2f}{tp2_str}\n"
            f"Horizon: {horizon.capitalize()}"
            f"{notion_note}"
        )

    return None


def process_task(prompt, category=None, *args, image_b64=None, mime_type="image/jpeg", **kwargs):
    print(f"--- Processing [{category}]: {prompt[:60] if prompt else '[image only]'} ---")
    start = time.time()

    # Scanner/watchlist/trade commands intercept before LLM pipeline
    if not image_b64:
        try:
            cmd_response = _handle_scanner_command(prompt)
            if cmd_response is not None:
                return cmd_response
        except Exception as e:
            print(f"[CMD] Handler error: {e}")

    # Verified snapshot flow: two API calls 60s apart + Notion log
    if category == "financial" and not image_b64 and _is_snapshot_request(prompt):
        try:
            from skills.snapshot_logger import run_verified_snapshot
            asset   = _detect_asset(prompt)
            horizon = _detect_trade_horizon(prompt)
            result, flags = run_verified_snapshot(tag="manual", asset=asset, horizon=horizon)
            record_timing("financial", time.time() - start)
            return result
        except Exception as e:
            print(f"Verified snapshot failed, falling back: {e}")

    content = _build_content(prompt, category, image_b64, mime_type)
    models = VISION_MODELS if image_b64 else TEXT_MODELS
    try:
        result = _call_model(models, content)
    except Exception as e:
        print(f"All models failed: {e}")
        result = f"API Error: {str(e)}"
    try:
        record_timing(category or "medium", time.time() - start)
    except Exception:
        pass
    # Auto-log chart trade ideas to Notion
    if image_b64:
        try:
            from skills.notion_logger import log_trade_idea
            notion_url = log_trade_idea(result)
            if notion_url:
                result += f"\n\n📓 _Logged to Notion_"
        except Exception as e:
            print(f"Notion log error: {e}")
    return result
