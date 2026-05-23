"""
Verified BTC snapshot: two API calls 60s apart, anomaly comparison, Notion log.
Called by the cron job and by Telegram snapshot requests.
"""

import os
import re
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv('/root/bastobot/.env')

NOTION_API_KEY   = os.getenv("NOTION_API_KEY")
NOTION_VERSION   = "2022-06-28"
SNAPSHOT_DB_ID   = "36970a02-6811-819d-8132-dc53402347cb"

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

    # 4. Liquidation magnitude sanity
    if "liquidations" in d1:
        total = d1["liquidations"]["total_liq_usd"]
        if total > 2_000_000_000:
            flags.append(f"🚨 Liq total ${total:,.0f} exceeds $2B — data suspect")
        elif total < 50_000:
            flags.append(f"⚠️ Liq total ${total:,.0f} unusually low — possible feed issue")

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

def log_snapshot_to_notion(snapshot_text: str, data: dict, flags: list[str], tag: str = "scheduled") -> str | None:
    if not NOTION_API_KEY:
        return None

    now = datetime.now(timezone.utc)
    title = f"BTC Snapshot — {now.strftime('%b %d, %Y %H:%M')} UTC"
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


# ── Main entry point ──────────────────────────────────────────────────────────

def run_verified_snapshot(tag: str = "scheduled") -> tuple[str, list[str]]:
    """
    Two API calls 60s apart. Returns (snapshot_text, flags).
    Logs to Notion automatically.
    """
    import sys
    sys.path.insert(0, '/root/bastobot')
    from skills.trading import get_btc_analysis
    from workers.tasks import _fetch_market_data, _call_model, TEXT_MODELS, TRADING_INSTRUCTION

    print(f"[SNAPSHOT] Call 1 of 2 (tag={tag})")
    data1 = get_btc_analysis()

    print("[SNAPSHOT] Waiting 60s for call 2...")
    time.sleep(60)

    print("[SNAPSHOT] Call 2 of 2")
    data2 = get_btc_analysis()

    flags = validate_snapshot(data1, data2)

    # Use call-2 data for the snapshot (more recent), but flag if suspect
    market_text = _fetch_market_data()
    flag_header = ""
    if flags:
        suspect = any("🚨" in f for f in flags)
        icon = "🚨 SUSPECT DATA" if suspect else "⚠️ DATA FLAGS"
        flag_header = f"[{icon}: {'; '.join(flags)}]\n\n"

    prompt = f"{TRADING_INSTRUCTION}\n\n{flag_header}btc snapshot\n\n{market_text}"
    snapshot_text = _call_model(TEXT_MODELS, prompt)

    notion_url = log_snapshot_to_notion(snapshot_text, data2, flags, tag)
    if notion_url:
        snapshot_text += f"\n\n📓 _Logged to Notion_"

    return snapshot_text, flags


if __name__ == "__main__":
    text, flags = run_verified_snapshot(tag="manual")
    print("\n" + "="*60)
    print(text)
    if flags:
        print("\nFLAGS:")
        for f in flags:
            print(f"  {f}")
