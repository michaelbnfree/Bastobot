"""
Verified BTC snapshot: two API calls 60s apart, anomaly comparison, Notion log,
JSONL data file, and GitHub Issues for suspect snapshots.
Called by the cron job and by Telegram snapshot requests.
"""

import os
import re
import json
import time
import subprocess
import requests
import redis as _redis_lib
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv('/root/bastobot/.env')

NOTION_API_KEY   = os.getenv("NOTION_API_KEY")
NOTION_VERSION   = "2022-06-28"
SNAPSHOT_DB_ID   = "36970a02-6811-819d-8132-dc53402347cb"
GITHUB_TOKEN     = os.getenv("GITHUB_TOKEN")
GITHUB_REPO      = "michaelbnfree/Bastobot"
JSONL_PATH       = "/root/bastobot/data/snapshots.jsonl"

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}


# ── Validation ────────────────────────────────────────────────────────────────

def validate_snapshot(d1: dict, d2: dict | None = None) -> list[str]:
    """
    Returns a list of human-readable flag strings.
    d1 = first call data, d2 = second call data (60s later), optional.
    """
    flags = []

    # 1. Source errors from first call
    for k in d1:
        if k.endswith("_error"):
            flags.append(f"⚠️ Source error ({k.replace('_error','')}): {d1[k]}")

    # 2. Cross-source spot price agreement (should be within 0.3%)
    prices = {}
    if "binance" in d1:
        prices["binance"] = d1["binance"]["price"]
    if "derivatives" in d1:
        prices["binance_mark"] = d1["derivatives"]["mark_price"]
    if "bybit" in d1:
        prices["bybit_mark"] = d1["bybit"]["mark_price"]
    if len(prices) >= 2:
        vals = list(prices.values())
        dev_pct = (max(vals) - min(vals)) / min(vals) * 100
        if dev_pct > 0.5:
            flags.append(f"🚨 Price spread {dev_pct:.2f}% across sources: {prices}")

    # 3. Funding rate sign consensus (all three should agree)
    funding = {}
    if "derivatives" in d1:
        funding["binance"] = d1["derivatives"]["funding_rate_pct"]
    if "bybit" in d1:
        funding["bybit"] = d1["bybit"]["funding_rate_pct"]
    if "okx" in d1:
        funding["okx"] = d1["okx"]["funding_rate_pct"]
    if len(funding) >= 2:
        signs = {k: (v > 0) for k, v in funding.items()}
        if len(set(signs.values())) > 1:
            flags.append(f"⚠️ Funding sign mismatch: {funding}")

    # 4. Liquidation magnitude sanity + cross-source consistency
    if "liquidations" in d1:
        liq = d1["liquidations"]
        total = liq["total_liq_usd"]
        if total > 2_000_000_000:
            flags.append(f"🚨 Liq total ${total:,.0f} exceeds $2B — data suspect")
        elif total < 50_000:
            flags.append(f"⚠️ Liq total ${total:,.0f} unusually low — possible feed issue")
        if liq.get("gate_excluded"):
            flags.append(f"⚠️ Gate.io liq excluded (10x outlier vs OKX: gate=${liq['gate_liq_usd']:,}  okx=${liq['okx_liq_usd']:,})")
        elif liq.get("okx_liq_usd") and liq.get("gate_liq_usd"):
            ok, ga = liq["okx_liq_usd"], liq["gate_liq_usd"]
            if ok > 0 and ga > 0:
                ratio = max(ok, ga) / min(ok, ga)
                if ratio > 5:
                    flags.append(f"⚠️ Liq source divergence {ratio:.1f}x: OKX=${ok:,}  Gate=${ga:,} — treat total as approximate")

    # 4b. Per-field absolute bounds
    btc_price = d1.get("binance", {}).get("price")
    if btc_price and not (1_000 < btc_price < 500_000):
        flags.append(f"🚨 BTC price ${btc_price:,.0f} outside valid range — bad data")
    for exch, src in [("binance", d1.get("derivatives", {})),
                      ("bybit",   d1.get("bybit", {})),
                      ("okx",     d1.get("okx", {}))]:
        fr = src.get("funding_rate_pct")
        if fr is not None and abs(fr) > 0.5:
            flags.append(f"🚨 {exch} funding rate {fr:+.4f}% out of normal range (>0.5%) — possible bad data")

    # 5. Two-call comparison (d2 is 60s after d1)
    if d2:
        # Price drift
        p1 = d1.get("binance", {}).get("price", 0)
        p2 = d2.get("binance", {}).get("price", 0)
        if p1 and p2:
            drift = abs(p2 - p1) / p1 * 100
            if drift == 0.0:
                flags.append(f"⚠️ Price identical between calls (${p1:,.2f}) — possible stale cache")
            elif drift > 1.0:
                flags.append(f"⚠️ Price moved {drift:.2f}% in 60s: ${p1:,.2f} → ${p2:,.2f}")

        # OI consistency
        oi1 = d1.get("derivatives", {}).get("oi_usd_bn", 0)
        oi2 = d2.get("derivatives", {}).get("oi_usd_bn", 0)
        if oi1 and oi2:
            oi_drift = abs(oi2 - oi1) / oi1 * 100
            if oi_drift > 5:
                flags.append(f"⚠️ OI diverged {oi_drift:.1f}% between calls: ${oi1}B → ${oi2}B")

        # Funding rate sign flip between calls
        fr1 = d1.get("derivatives", {}).get("funding_rate_pct")
        fr2 = d2.get("derivatives", {}).get("funding_rate_pct")
        if fr1 is not None and fr2 is not None:
            if (fr1 > 0) != (fr2 > 0):
                flags.append(f"🚨 Funding rate sign flipped between calls: {fr1:+.4f}% → {fr2:+.4f}%")

        # Source reliability: errors on call 2 that weren't on call 1
        errors1 = {k.replace("_error", "") for k in d1 if k.endswith("_error")}
        errors2 = {k.replace("_error", "") for k in d2 if k.endswith("_error")}
        new_failures = errors2 - errors1
        if new_failures:
            flags.append(f"⚠️ Sources failed on 2nd call only: {new_failures} — treat as unreliable")
        recovered = errors1 - errors2
        if recovered:
            flags.append(f"ℹ️ Sources recovered by 2nd call: {recovered}")

    return flags


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_bias(text: str) -> str:
    t = text.lower()
    if "bias: bullish" in t or "bullish" in t[:300]:
        return "Bullish"
    if "bias: bearish" in t or "bearish" in t[:300]:
        return "Bearish"
    if "sideways" in t[:300]:
        return "Sideways"
    return "Neutral"


def _avg_funding(data: dict) -> float | None:
    rates = []
    if "derivatives" in data:
        rates.append(data["derivatives"]["funding_rate_pct"])
    if "bybit" in data:
        rates.append(data["bybit"]["funding_rate_pct"])
    if "okx" in data:
        rates.append(data["okx"]["funding_rate_pct"])
    return round(sum(rates) / len(rates), 4) if rates else None


# ── Notion logger ─────────────────────────────────────────────────────────────

def log_snapshot_to_notion(snapshot_text: str, data: dict, flags: list[str], tag: str = "scheduled", asset: str = "BTC") -> str | None:
    if not NOTION_API_KEY:
        return None

    now = datetime.now(timezone.utc)
    title = f"{asset} Snapshot — {now.strftime('%b %d, %Y %H:%M')} UTC"
    binance = data.get("binance", {})
    ta_1d   = data.get("ta", {}).get("1d", {})

    flag_text = "\n".join(flags) if flags else "✅ No anomalies"
    page_text = f"{snapshot_text}\n\n---\nDATA FLAGS\n{flag_text}"

    properties = {
        "Title":       {"title": [{"text": {"content": title}}]},
        "Timestamp":   {"date": {"start": now.isoformat()}},
        "Tag":         {"select": {"name": tag}},
        "Flag Count":  {"number": len(flags)},
        "Suspect":     {"checkbox": any("🚨" in f for f in flags)},
    }
    if binance.get("price"):
        properties["Price"] = {"number": binance["price"]}
    if binance.get("change_24h_pct") is not None:
        properties["Change 24h"] = {"number": round(binance["change_24h_pct"] / 100, 4)}
    if binance.get("change_7d_pct") is not None:
        properties["Change 7d"] = {"number": round(binance["change_7d_pct"] / 100, 4)}
    if ta_1d.get("rsi"):
        properties["RSI 1d"] = {"number": ta_1d["rsi"]}
    avg_fr = _avg_funding(data)
    if avg_fr is not None:
        properties["Funding Avg"] = {"number": avg_fr}
    derivatives = data.get("derivatives", {})
    if derivatives.get("oi_usd_bn"):
        bybit_oi = data.get("bybit", {}).get("oi_usd_bn", 0)
        okx_oi   = data.get("okx", {}).get("oi_usd_bn", 0)
        properties["OI Total B"] = {"number": round(derivatives["oi_usd_bn"] + bybit_oi + okx_oi, 2)}
    if data.get("liquidations", {}).get("total_liq_usd"):
        properties["Liq Total"] = {"number": data["liquidations"]["total_liq_usd"]}

    bias = _extract_bias(snapshot_text)
    properties["Bias"] = {"select": {"name": bias}}

    # Truncate page body to Notion's 2000-char rich_text limit per block
    chunks = [page_text[i:i+2000] for i in range(0, min(len(page_text), 6000), 2000)]
    children = [
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": [{"text": {"content": chunk}}]}}
        for chunk in chunks
    ]

    try:
        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers=HEADERS,
            json={"parent": {"database_id": SNAPSHOT_DB_ID}, "properties": properties, "children": children},
            timeout=15,
        )
        r.raise_for_status()
        url = r.json().get("url", "")
        print(f"[SNAPSHOT] Logged: {title} → {url}")
        return url
    except Exception as e:
        print(f"[SNAPSHOT] Notion log failed: {e}")
        return None


# ── JSONL data log ────────────────────────────────────────────────────────────

def append_to_jsonl(data: dict, flags: list[str], tag: str, notion_url: str | None = None,
                    bias: str | None = None, asset: str = "BTC") -> None:
    """Append one line to data/snapshots.jsonl for the full queryable dataset."""
    now = datetime.now(timezone.utc)
    binance     = data.get("binance", {})
    ta_1h       = data.get("ta", {}).get("1h", {})
    ta_4h       = data.get("ta", {}).get("4h", {})
    ta_1d       = data.get("ta", {}).get("1d", {})
    derivatives = data.get("derivatives", {})
    bybit_oi    = data.get("bybit", {}).get("oi_usd_bn", 0)
    okx_oi      = data.get("okx", {}).get("oi_usd_bn", 0)
    regime      = _BIAS_TO_REGIME.get(bias or "", "CRAB") if bias else None

    row = {
        "timestamp":           now.isoformat(),
        "asset":               asset,
        "tag":                 tag,
        "bias":                bias,
        "regime":              regime,
        # Price
        "price":               binance.get("price"),
        "change_24h_pct":      binance.get("change_24h_pct"),
        "change_7d_pct":       binance.get("change_7d_pct"),
        "high_24h":            binance.get("high_24h"),
        "low_24h":             binance.get("low_24h"),
        "volume_change_pct":   binance.get("volume_change_pct"),
        # TA — multi-TF
        "signal_1h":           ta_1h.get("summary", {}).get("RECOMMENDATION"),
        "signal_4h":           ta_4h.get("summary", {}).get("RECOMMENDATION"),
        "signal_1d":           ta_1d.get("summary", {}).get("RECOMMENDATION"),
        "rsi_1h":              ta_1h.get("rsi"),
        "rsi_4h":              ta_4h.get("rsi"),
        "rsi_1d":              ta_1d.get("rsi"),
        "adx_1d":              ta_1d.get("adx"),
        "macd_1d":             ta_1d.get("macd"),
        "ema_20_1d":           ta_1d.get("ema_20"),
        "ema_50_1d":           ta_1d.get("ema_50"),
        "ema_200_1d":          ta_1d.get("ema_200"),
        "bb_upper_1d":         ta_1d.get("bb_upper"),
        "bb_lower_1d":         ta_1d.get("bb_lower"),
        # Derivatives
        "funding_binance":     derivatives.get("funding_rate_pct"),
        "funding_bybit":       data.get("bybit", {}).get("funding_rate_pct"),
        "funding_okx":         data.get("okx", {}).get("funding_rate_pct"),
        "funding_avg":         _avg_funding(data),
        "taker_buy_sell":      derivatives.get("taker_buy_sell_ratio"),
        "oi_total_bn":         round(derivatives.get("oi_usd_bn", 0) + bybit_oi + okx_oi, 2),
        "oi_change_24h":       derivatives.get("oi_change_24h_pct"),
        # Liquidations
        "liq_longs_usd":       data.get("liquidations", {}).get("longs_liq_usd"),
        "liq_shorts_usd":      data.get("liquidations", {}).get("shorts_liq_usd"),
        "liq_total_usd":       data.get("liquidations", {}).get("total_liq_usd"),
        "liq_change_pct":      data.get("liquidations", {}).get("change_pct"),
        # Positioning
        "ls_global":           derivatives.get("global_ls_ratio"),
        "ls_top_traders":      derivatives.get("top_trader_ls_ratio"),
        # Sentiment
        "fear_greed":          data.get("fear_greed", {}).get("score"),
        "btc_dominance":       data.get("market", {}).get("btc_dominance_pct"),
        # Quality
        "flag_count":          len(flags),
        "suspect":             any("🚨" in f for f in flags),
        "flags":               flags,
        "notion_url":          notion_url,
    }
    try:
        with open(JSONL_PATH, "a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"[JSONL] Appended row for {now.strftime('%H:%M UTC')}")
    except Exception as e:
        print(f"[JSONL] Write failed: {e}")


# ── GitHub Issue for suspect snapshots ───────────────────────────────────────

def open_github_issue(flags: list[str], data: dict, notion_url: str | None, tag: str) -> str | None:
    """Opens a GitHub Issue when a snapshot is marked suspect (🚨 flags present)."""
    if not GITHUB_TOKEN:
        print("[GH] No GITHUB_TOKEN — skipping issue")
        return None

    now = datetime.now(timezone.utc)
    title = f"🚨 Suspect snapshot — {now.strftime('%b %d, %Y %H:%M UTC')} ({tag})"
    price = data.get("binance", {}).get("price")
    price_str = f"${price:,.2f}" if price else "unknown"

    flag_lines = "\n".join(f"- {f}" for f in flags)
    notion_link = f"\n\n**Notion page:** {notion_url}" if notion_url else ""
    body = (
        f"## Data anomaly detected\n\n"
        f"**Time:** {now.strftime('%Y-%m-%d %H:%M UTC')}  \n"
        f"**Price at snapshot:** {price_str}  \n"
        f"**Tag:** {tag}\n\n"
        f"### Flags\n{flag_lines}"
        f"{notion_link}\n\n"
        f"---\n"
        f"*Auto-opened by Barry's snapshot pipeline. "
        f"Investigate the flagged sources before using this snapshot for analysis.*"
    )
    try:
        r = requests.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/issues",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"title": title, "body": body, "labels": ["snapshot", "suspect-data", "data-quality"]},
            timeout=15,
        )
        r.raise_for_status()
        url = r.json().get("html_url", "")
        print(f"[GH] Issue opened: {url}")
        return url
    except Exception as e:
        print(f"[GH] Issue error: {e}")
    return None


# ── Main entry point ──────────────────────────────────────────────────────────

def run_verified_snapshot(tag: str = "scheduled", asset: str = "BTC", horizon: str = "swing") -> tuple[str, list[str]]:
    """
    Two API calls 60s apart. Returns (snapshot_text, flags).
    Logs to Notion, JSONL, and GitHub (if suspect).
    """
    import sys
    sys.path.insert(0, '/root/bastobot')
    from skills.trading import get_btc_analysis, get_asset_analysis
    from workers.tasks import _fetch_market_data, _call_model, TEXT_MODELS, build_snapshot_instruction, _HORIZON_META

    candles = _HORIZON_META.get(horizon, _HORIZON_META["swing"])["candles"]
    fetch = (lambda: get_btc_analysis(candles=candles)) if asset == "BTC" else (lambda: get_asset_analysis(asset, candles=candles))

    print(f"[SNAPSHOT] Call 1 of 2 (tag={tag}, asset={asset})")
    data1 = fetch()

    print("[SNAPSHOT] Waiting 60s for call 2...")
    time.sleep(60)

    print("[SNAPSHOT] Call 2 of 2")
    data2 = fetch()

    flags = validate_snapshot(data1, data2)
    suspect = any("🚨" in f for f in flags)

    # Use call-2 data for the snapshot (more recent), but scrub suspect sources
    scrubbed = dict(data2)
    if suspect:
        # Identify which sources are flagged and remove them from the data block
        flagged_text = " ".join(flags).lower()
        if "liq" in flagged_text and ("🚨" in " ".join(f for f in flags if "liq" in f.lower() or "gate" in f.lower())):
            scrubbed.pop("liquidations", None)
            print("[SNAPSHOT] Liquidation data scrubbed from prompt due to 🚨 flag")
        if "price" in flagged_text and "outside valid range" in flagged_text:
            scrubbed.pop("binance", None)
            print("[SNAPSHOT] Binance price data scrubbed from prompt due to 🚨 flag")
        if "funding rate" in flagged_text:
            for src in ["derivatives", "bybit", "okx"]:
                if any(src in f for f in flags if "🚨" in f):
                    scrubbed.pop(src, None)
                    print(f"[SNAPSHOT] {src} data scrubbed from prompt due to 🚨 funding flag")

    market_text = _fetch_market_data(asset, candles=candles)
    flag_header = ""
    if flags:
        icon = "🚨 SUSPECT DATA — some sources scrubbed" if suspect else "⚠️ DATA FLAGS"
        flag_header = f"[{icon}: {'; '.join(flags)}]\n\n"

    prev_idea = _get_prev_trade_idea(asset)
    prev_context = ""
    if prev_idea:
        try:
            then = datetime.fromisoformat(prev_idea["ts"])
            mins = int((datetime.now(timezone.utc) - then).total_seconds() / 60)
            prev_context = (
                f"[PRIOR TRADE IDEA — {mins}min ago, {asset} was ${prev_idea['price']:,.0f}, "
                f"horizon={prev_idea['horizon']}]\n"
                f"{prev_idea['text']}\n\n"
                f"Assess whether the above remains valid given current data. "
                f"If conditions changed materially, explain what changed and update the setup. "
                f"If still valid, confirm it explicitly rather than silently generating a contradictory one.\n\n"
            )
        except Exception:
            pass

    instruction = build_snapshot_instruction(horizon, asset)
    prompt = f"{instruction}\n\n{flag_header}{prev_context}{asset.lower()} snapshot\n\n{market_text}"
    snapshot_text = _call_model(TEXT_MODELS, prompt)
    _store_trade_idea(snapshot_text, data2, asset, horizon)

    bias = _extract_bias(snapshot_text)
    notion_url = log_snapshot_to_notion(snapshot_text, data2, flags, tag, asset)

    append_to_jsonl(data2, flags, tag, notion_url, bias=bias, asset=asset)

    if suspect:
        open_github_issue(flags, data2, notion_url, tag)

    if notion_url:
        snapshot_text += f"\n\n📓 _Logged to Notion_"

    # Write market regime to Redis for consumption by other systems
    _publish_regime(bias, data2, asset)

    return snapshot_text, flags


_BIAS_TO_REGIME = {
    "Bullish":  "BULL",
    "Bearish":  "BEAR",
    "Sideways": "CRAB",
    "Neutral":  "CRAB",
}
_REDIS = None

def _get_redis():
    global _REDIS
    if _REDIS is None:
        _REDIS = _redis_lib.Redis(host="localhost", port=6379, db=0)
    return _REDIS


def _get_prev_trade_idea(asset: str) -> dict | None:
    try:
        raw = _get_redis().get(f"trade_idea:{asset}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _store_trade_idea(text: str, data: dict, asset: str, horizon: str) -> None:
    try:
        match = re.search(r'(━━━ PRIMARY SETUP.*)', text, re.DOTALL)
        if not match:
            return
        setup_text = match.group(1).strip()[:900]
        payload = {
            "ts":      datetime.now(timezone.utc).isoformat(),
            "price":   data.get("binance", {}).get("price"),
            "horizon": horizon,
            "text":    setup_text,
        }
        _get_redis().setex(f"trade_idea:{asset}", 86400, json.dumps(payload))
        print(f"[TRADE] Cached {horizon} setup for {asset}")
    except Exception as e:
        print(f"[TRADE] Cache failed: {e}")

def _ta_to_regime(rec: str) -> str:
    u = (rec or "").upper()
    if "BUY" in u:  return "BULL"
    if "SELL" in u: return "BEAR"
    return "CRAB"

def _publish_regime(bias: str, data: dict, asset: str = "BTC") -> None:
    regime = _BIAS_TO_REGIME.get(bias, "CRAB")

    ta   = data.get("ta", {})
    r_1h = _ta_to_regime(ta.get("1h", {}).get("summary", {}).get("RECOMMENDATION", ""))
    r_4h = _ta_to_regime(ta.get("4h", {}).get("summary", {}).get("RECOMMENDATION", ""))

    meta = {
        "regime":     regime,
        "regime_1h":  r_1h,
        "regime_4h":  r_4h,
        "bias":       bias,
        "asset":      asset,
        "price":      data.get("binance", {}).get("price"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        r = _get_redis()
        r.setex("market:regime",      14400, regime)           # 4h TTL
        r.setex("market:regime:1h",   14400, r_1h)
        r.setex("market:regime:4h",   14400, r_4h)
        r.setex("market:regime_meta", 14400, json.dumps(meta))
        print(f"[REGIME] Published overall={regime} 1h={r_1h} 4h={r_4h} (bias={bias}, asset={asset})")
    except Exception as e:
        print(f"[REGIME] Redis write failed: {e}")


if __name__ == "__main__":
    text, flags = run_verified_snapshot(tag="manual")
    print("\n" + "="*60)
    print(text)
    if flags:
        print("\nFLAGS:")
        for f in flags:
            print(f"  {f}")
