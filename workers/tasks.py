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

Bias: [one line — direction + condition needed to confirm]
- Bullish flip: [trigger] → [target]
- Bearish flip: [trigger] → [target]

[If a clear setup exists, add one line: the trade, entry zone, target, invalidation.]

For trade setup requests (entry/target/invalidation), lead with the setup bias then give Entry, Target(s), Invalidation each on their own line, supported by the most relevant data points.

For simple price questions, give a direct 2-3 line answer. Always lead with the conclusion. No filler."""

def _fetch_market_data():
    try:
        from skills.trading import get_btc_analysis
        from skills.time import get_time_context
        d = get_btc_analysis()
        if not isinstance(d, dict):
            return None

        from datetime import datetime
        lines = [f"[LIVE MARKET DATA — BTC/USDT — {datetime.utcnow().strftime('%b %d, %Y %H:%M UTC')}]"]

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

        # --- Multi-timeframe TA ---
        if "ta" in d:
            for tf in ("1h", "4h", "1d"):
                if tf not in d["ta"]:
                    continue
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
            lines.append(
                f"Binance Funding: {dv['funding_rate_pct']:+.4f}%  "
                f"Mark: ${dv['mark_price']:,.2f}  Premium: {dv['premium_pct']:+.4f}%"
            )
            lines.append(
                f"Global L/S: {dv['global_ls_ratio']:.3f} "
                f"({dv['global_longs_pct']}% long / {dv['global_shorts_pct']}% short)  "
                f"Top Traders: {dv['top_trader_ls_ratio']:.3f} "
                f"({dv['top_trader_longs_pct']}% long / {dv['top_trader_shorts_pct']}% short)"
            )
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
        market = _fetch_market_data()
        base = f"{TRADING_INSTRUCTION}\n\n{prompt}".strip()
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

_SNAPSHOT_KEYWORDS = ("snapshot", "market overview", "market update", "market check")

def _is_snapshot_request(prompt: str) -> bool:
    if not prompt:
        return False
    p = prompt.lower().strip()
    return any(kw in p for kw in _SNAPSHOT_KEYWORDS)


def process_task(prompt, category=None, *args, image_b64=None, mime_type="image/jpeg", **kwargs):
    print(f"--- Processing [{category}]: {prompt[:60] if prompt else '[image only]'} ---")
    start = time.time()

    # Verified snapshot flow: two API calls 60s apart + Notion log
    if category == "financial" and not image_b64 and _is_snapshot_request(prompt):
        try:
            from skills.snapshot_logger import run_verified_snapshot
            result, flags = run_verified_snapshot(tag="manual")
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
