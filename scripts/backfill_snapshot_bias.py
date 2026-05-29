"""
Backfill bias, regime, asset, and extended TA fields into snapshots.jsonl.

For each row with a valid Notion URL, fetches the Bias property from the
Notion page and adds bias + regime. Also stamps asset="BTC" (or detects ETH
from price < $10k) and adds null placeholders for the new TA fields so all
rows share a consistent schema.

Run once: python scripts/backfill_snapshot_bias.py
"""

import json
import os
import re
import time
import requests
from dotenv import load_dotenv

load_dotenv('/root/bastobot/.env')

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
JSONL_PATH     = "/root/bastobot/data/snapshots.jsonl"
BACKUP_PATH    = JSONL_PATH + ".bak"

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
}

BIAS_TO_REGIME = {
    "Bullish":  "BULL",
    "Bearish":  "BEAR",
    "Sideways": "CRAB",
    "Neutral":  "CRAB",
}

NEW_FIELDS = [
    "asset", "bias", "regime",
    "signal_1h", "signal_4h",
    "volume_change_pct",
    "macd_1d", "ema_20_1d", "ema_50_1d", "ema_200_1d",
    "bb_upper_1d", "bb_lower_1d",
    "taker_buy_sell", "liq_change_pct",
]


def extract_page_id(url: str) -> str | None:
    """Pull 32-char hex page ID from any Notion URL format."""
    m = re.search(r'([0-9a-f]{32})', url.replace('-', ''))
    return m.group(1) if m else None


def fetch_bias(page_id: str) -> str | None:
    """Call Notion API for the Bias select property of a page."""
    try:
        r = requests.get(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=HEADERS,
            timeout=10,
        )
        if r.status_code != 200:
            return None
        props = r.json().get("properties", {})
        bias_prop = props.get("Bias", {})
        select = bias_prop.get("select") or {}
        return select.get("name")
    except Exception as e:
        print(f"  [warn] fetch failed for {page_id}: {e}")
        return None


def main():
    # Backup
    with open(JSONL_PATH) as f:
        original = f.read()
    with open(BACKUP_PATH, "w") as f:
        f.write(original)
    print(f"Backup written to {BACKUP_PATH}")

    rows = [json.loads(line) for line in original.strip().splitlines()]
    print(f"Loaded {len(rows)} rows")

    updated = 0
    skipped = 0
    failed  = 0

    for i, row in enumerate(rows):
        # Detect asset from price
        price = row.get("price") or 0
        asset = "ETH" if 1000 < price < 10_000 else "BTC"

        # Stamp new fields with None if not present
        for field in NEW_FIELDS:
            if field not in row:
                row[field] = None
        row["asset"] = asset

        # Skip if bias already backfilled
        if row.get("bias") is not None:
            skipped += 1
            continue

        url = row.get("notion_url", "")
        if not url or "notion.so/test" in url or "notion.so" not in url:
            skipped += 1
            continue

        page_id = extract_page_id(url)
        if not page_id:
            skipped += 1
            continue

        bias = fetch_bias(page_id)
        if bias:
            row["bias"]   = bias
            row["regime"] = BIAS_TO_REGIME.get(bias, "CRAB")
            updated += 1
            print(f"  [{i+1}/{len(rows)}] {row['timestamp'][:16]}  bias={bias}  regime={row['regime']}")
        else:
            failed += 1
            print(f"  [{i+1}/{len(rows)}] {row['timestamp'][:16]}  no bias found")

        time.sleep(0.35)  # ~3 req/s Notion rate limit

    # Rewrite JSONL
    with open(JSONL_PATH, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    print()
    print(f"Done. Updated={updated}  Skipped={skipped}  Failed={failed}")
    print(f"Total rows: {len(rows)}")


if __name__ == "__main__":
    main()
