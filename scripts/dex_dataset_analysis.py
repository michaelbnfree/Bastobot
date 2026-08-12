#!/usr/bin/env python3
"""
DEX Arbitrage Dataset Analysis — analyze 3-month opportunity dataset.

Usage:
  python scripts/dex_dataset_analysis.py summary    # Overview stats
  python scripts/dex_dataset_analysis.py by-symbol  # Top symbols
  python scripts/dex_dataset_analysis.py by-chain   # By chain
  python scripts/dex_dataset_analysis.py by-dex     # By DEX
  python scripts/dex_dataset_analysis.py weekly     # Weekly trends
"""

import os
import sys
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import json

from dotenv import load_dotenv
load_dotenv("/root/bastobot/.env")

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_VERSION = "2022-06-28"
DATABASE_ID = os.getenv("NOTION_DEX_DATABASE_ID", "")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}


def query_database(days: int = 90):
    """Query all opportunities from last N days."""
    if not NOTION_API_KEY or not DATABASE_ID:
        print("❌ Missing NOTION_API_KEY or NOTION_DEX_DATABASE_ID")
        sys.exit(1)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    payload = {
        "filter": {
            "property": "Date",
            "date": {"on_or_after": cutoff},
        },
        "page_size": 100,
    }

    all_results = []
    has_more = True
    next_cursor = None

    try:
        while has_more:
            if next_cursor:
                payload["start_cursor"] = next_cursor

            r = requests.post(
                f"https://api.notion.com/v1/databases/{DATABASE_ID}/query",
                headers=HEADERS,
                json=payload,
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()

            results = data.get("results", [])
            all_results.extend(results)

            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")

        return all_results

    except Exception as e:
        print(f"❌ Query failed: {e}")
        sys.exit(1)


def parse_opportunity(page):
    """Extract opportunity data from Notion page."""
    props = page.get("properties", {})

    try:
        return {
            "date": props.get("Date", {}).get("date", {}).get("start"),
            "symbol": props.get("Symbol", {}).get("title", [{}])[0].get("text", {}).get("content"),
            "chain": props.get("Chain", {}).get("select", {}).get("name"),
            "dex": props.get("DEX", {}).get("rich_text", [{}])[0].get("text", {}).get("content"),
            "spread": props.get("Spread %", {}).get("number"),
            "cex_price": props.get("CEX Price", {}).get("number"),
            "dex_price": props.get("DEX Price", {}).get("number"),
            "liquidity": props.get("Liquidity", {}).get("number"),
            "volume_24h": props.get("Volume 24h", {}).get("number"),
            "status": props.get("Status", {}).get("select", {}).get("name"),
            "direction": props.get("Direction", {}).get("select", {}).get("name"),
        }
    except:
        return None


def cmd_summary(pages):
    """Overall statistics."""
    opps = [parse_opportunity(p) for p in pages]
    opps = [o for o in opps if o]

    if not opps:
        print("No data yet")
        return

    spreads = [abs(o["spread"]) for o in opps if o.get("spread")]
    liquidities = [o["liquidity"] for o in opps if o.get("liquidity")]

    print(f"\n{'='*70}")
    print(f"DEX Arbitrage Dataset Summary")
    print(f"{'='*70}\n")
    print(f"Total opportunities logged: {len(opps)}")
    print(f"Date range: {opps[-1]['date']} to {opps[0]['date']}")
    print(f"\nSpread Statistics:")
    print(f"  Average spread:  {sum(spreads) / len(spreads):.2f}%")
    print(f"  Median spread:   {sorted(spreads)[len(spreads)//2]:.2f}%")
    print(f"  Max spread:      {max(spreads):.2f}%")
    print(f"\nLiquidity Statistics:")
    print(f"  Avg liquidity:   ${sum(liquidities) / len(liquidities):,.0f}")
    print(f"  Median:          ${sorted(liquidities)[len(liquidities)//2]:,.0f}")
    print(f"  Max:             ${max(liquidities):,.0f}")
    print(f"  Min:             ${min(liquidities):,.0f}")

    # Count by status
    statuses = defaultdict(int)
    for o in opps:
        if o.get("status"):
            statuses[o["status"]] += 1

    print(f"\nBy Status:")
    for status, count in sorted(statuses.items(), key=lambda x: x[1], reverse=True):
        print(f"  {status:15s}: {count:3d}")

    print(f"\n{'='*70}\n")


def cmd_by_symbol(pages):
    """Top symbols."""
    opps = [parse_opportunity(p) for p in pages]
    opps = [o for o in opps if o]

    symbols = defaultdict(lambda: {"count": 0, "spreads": [], "liq": []})

    for o in opps:
        if o.get("symbol"):
            symbols[o["symbol"]]["count"] += 1
            if o.get("spread"):
                symbols[o["symbol"]]["spreads"].append(abs(o["spread"]))
            if o.get("liquidity"):
                symbols[o["symbol"]]["liq"].append(o["liquidity"])

    print(f"\n{'='*70}")
    print(f"Opportunities by Symbol (Top 20)")
    print(f"{'='*70}\n")

    for symbol, data in sorted(symbols.items(), key=lambda x: x[1]["count"], reverse=True)[:20]:
        avg_spread = sum(data["spreads"]) / len(data["spreads"]) if data["spreads"] else 0
        avg_liq = sum(data["liq"]) / len(data["liq"]) if data["liq"] else 0
        print(
            f"{symbol:8s}: {data['count']:3d} opps | "
            f"Avg spread {avg_spread:.2f}% | "
            f"Avg liq ${avg_liq:>12,.0f}"
        )

    print(f"\n{'='*70}\n")


def cmd_by_chain(pages):
    """By chain."""
    opps = [parse_opportunity(p) for p in pages]
    opps = [o for o in opps if o]

    chains = defaultdict(lambda: {"count": 0, "spreads": []})

    for o in opps:
        if o.get("chain"):
            chains[o["chain"]]["count"] += 1
            if o.get("spread"):
                chains[o["chain"]]["spreads"].append(abs(o["spread"]))

    print(f"\n{'='*70}")
    print(f"Opportunities by Chain")
    print(f"{'='*70}\n")

    for chain, data in sorted(chains.items(), key=lambda x: x[1]["count"], reverse=True):
        avg_spread = sum(data["spreads"]) / len(data["spreads"]) if data["spreads"] else 0
        print(f"{chain:15s}: {data['count']:3d} opps | Avg spread {avg_spread:.2f}%")

    print(f"\n{'='*70}\n")


def cmd_by_dex(pages):
    """By DEX."""
    opps = [parse_opportunity(p) for p in pages]
    opps = [o for o in opps if o]

    dexes = defaultdict(lambda: {"count": 0, "spreads": []})

    for o in opps:
        if o.get("dex"):
            dexes[o["dex"]]["count"] += 1
            if o.get("spread"):
                dexes[o["dex"]]["spreads"].append(abs(o["spread"]))

    print(f"\n{'='*70}")
    print(f"Opportunities by DEX")
    print(f"{'='*70}\n")

    for dex, data in sorted(dexes.items(), key=lambda x: x[1]["count"], reverse=True):
        avg_spread = sum(data["spreads"]) / len(data["spreads"]) if data["spreads"] else 0
        print(f"{dex:20s}: {dex['count']:3d} opps | Avg spread {avg_spread:.2f}%")

    print(f"\n{'='*70}\n")


def cmd_weekly(pages):
    """Weekly trends."""
    opps = [parse_opportunity(p) for p in pages]
    opps = [o for o in opps if o and o.get("date")]

    # Group by week
    weeks = defaultdict(lambda: {"count": 0, "spreads": [], "dexes": set()})

    for o in opps:
        date = datetime.fromisoformat(o["date"])
        week_start = (date - timedelta(days=date.weekday())).strftime("%Y-W%W")
        weeks[week_start]["count"] += 1
        if o.get("spread"):
            weeks[week_start]["spreads"].append(abs(o["spread"]))
        if o.get("dex"):
            weeks[week_start]["dexes"].add(o["dex"])

    print(f"\n{'='*70}")
    print(f"Weekly Trends")
    print(f"{'='*70}\n")

    for week in sorted(weeks.keys()):
        data = weeks[week]
        avg_spread = sum(data["spreads"]) / len(data["spreads"]) if data["spreads"] else 0
        print(
            f"{week}: {data['count']:3d} opps | "
            f"Avg spread {avg_spread:.2f}% | "
            f"DEXes: {len(data['dexes'])}"
        )

    print(f"\n{'='*70}\n")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Analyze DEX arbitrage dataset")
    parser.add_argument(
        "command",
        choices=["summary", "by-symbol", "by-chain", "by-dex", "weekly"],
        help="Analysis type"
    )
    parser.add_argument("--days", type=int, default=90, help="Days to analyze (default 90)")

    args = parser.parse_args()

    print(f"\n📊 Fetching opportunities (last {args.days} days)...")
    pages = query_database(days=args.days)
    print(f"✅ Found {len(pages)} opportunities\n")

    commands = {
        "summary": cmd_summary,
        "by-symbol": cmd_by_symbol,
        "by-chain": cmd_by_chain,
        "by-dex": cmd_by_dex,
        "weekly": cmd_weekly,
    }

    commands[args.command](pages)


if __name__ == "__main__":
    main()
