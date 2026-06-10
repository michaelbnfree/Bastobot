"""
One-time setup: creates the 3 new Notion databases for the scanner system.
Run: python3 scripts/setup_notion.py <parent_page_id>

The parent_page_id is any Notion page where you want the databases created.
Get it from a Notion page URL: notion.so/your-workspace/<PAGE_ID>

After running, add the printed IDs to your .env:
  NOTION_CHAIN_SNAPSHOTS_DB_ID=...
  NOTION_TRADE_MONITOR_DB_ID=...
  NOTION_HOT_TRADES_DB_ID=...

Then restart the scanner service:
  systemctl restart bastobot-scanner
"""

import os
import sys
import json
import requests
from dotenv import load_dotenv

load_dotenv("/root/bastobot/.env")

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_VERSION = "2022-06-28"
HEADERS = {
    "Authorization":  f"Bearer {NOTION_API_KEY}",
    "Content-Type":   "application/json",
    "Notion-Version": NOTION_VERSION,
}

ECOSYSTEMS = [
    "Bitcoin", "Ethereum", "Solana", "BNB Chain", "Avalanche",
    "PoW", "Monad", "XRP Ledger", "Cardano", "Polkadot",
    "Cosmos", "NEAR", "Aptos", "Sui", "Celestia", "Injective",
    "TON", "Tron", "Hedera", "Unknown",
]

DATABASES = {
    "Chain Snapshots": {
        "description": "Multi-asset snapshots organised by chain/ecosystem (non-BTC).",
        "properties": {
            "Title":       {"title": {}},
            "Timestamp":   {"date": {}},
            "Asset":       {"select": {"options": [{"name": s, "color": "default"} for s in [
                "ETH","SOL","BNB","AVAX","MATIC","ARB","OP","LINK","UNI","DOGE","LTC","BCH",
                "JUP","WIF","BONK","MON","XRP","ADA","DOT","ATOM","APT","SUI","TON","TRX",
            ]]}},
            "Chain":       {"select": {"options": [{"name": s, "color": "default"} for s in [
                "ETH","SOL","BNB","AVAX","LTC","BCH","DOGE","XRP","ADA","DOT","ATOM","MON","TON","TRX",
            ]]}},
            "Ecosystem":   {"select": {"options": [{"name": s, "color": "default"} for s in ECOSYSTEMS]}},
            "Tag":         {"select": {"options": [{"name": s, "color": "default"} for s in [
                "session-asia","session-london","session-ny","candle-4h","manual","alert",
            ]]}},
            "Price":       {"number": {"format": "dollar"}},
            "RSI 1d":      {"number": {"format": "number"}},
            "Bias":        {"select": {"options": [{"name": s, "color": "default"} for s in ["Bullish","Bearish","Sideways","Neutral"]]}},
            "Conviction":  {"select": {"options": [{"name": s, "color": "default"} for s in ["Very High","High","Medium","Low"]]}},
            "Flag Count":  {"number": {"format": "number"}},
            "Suspect":     {"checkbox": {}},
            "Change 24h":  {"number": {"format": "percent"}},
            "Funding Avg": {"number": {"format": "number"}},
        },
    },
    "Trade Monitor": {
        "description": "Track trade setups with entry, SL, TP1, TP2. Auto-updated by the scanner.",
        "properties": {
            "Title":       {"title": {}},
            "Asset":       {"select": {"options": [{"name": s, "color": "default"} for s in [
                "BTC","ETH","SOL","BNB","AVAX","MATIC","ARB","OP","LINK","DOGE","LTC","BCH",
                "JUP","WIF","BONK","XRP","ADA","APT","SUI","TON",
            ]]}},
            "Direction":   {"select": {"options": [{"name": "Long","color":"green"},{"name": "Short","color":"red"}]}},
            "Horizon":     {"select": {"options": [{"name": s, "color": "default"} for s in ["Scalp","Day","Swing","Position"]]}},
            "Entry":       {"number": {"format": "dollar"}},
            "SL":          {"number": {"format": "dollar"}},
            "TP1":         {"number": {"format": "dollar"}},
            "TP2":         {"number": {"format": "dollar"}},
            "Outcome %":   {"number": {"format": "percent"}},
            "Status":      {"select": {"options": [{"name": s, "color": "default"} for s in ["Open","TP1 Hit","TP2 Hit","SL Hit","Closed"]]}},
            "Conviction":  {"select": {"options": [{"name": s, "color": "default"} for s in ["Very High","High","Medium","Low"]]}},
            "Session":     {"select": {"options": [{"name": s, "color": "default"} for s in ["asia","london","ny","manual"]]}},
            "Date":        {"date": {}},
            "Notes":       {"rich_text": {}},
        },
    },
    "Hot Trades": {
        "description": "High-conviction setups surfaced automatically by the scanner (score ≥ 6.5/10).",
        "properties": {
            "Title":       {"title": {}},
            "Asset":       {"select": {"options": [{"name": s, "color": "default"} for s in [
                "BTC","ETH","SOL","BNB","AVAX","MATIC","ARB","OP","DOGE","LTC","JUP","WIF",
            ]]}},
            "Direction":   {"select": {"options": [{"name": "Bullish","color":"green"},{"name": "Bearish","color":"red"}]}},
            "Horizon":     {"select": {"options": [{"name": s, "color": "default"} for s in ["Scalp","Day","Swing","Position"]]}},
            "Score":       {"number": {"format": "number"}},
            "Conviction":  {"select": {"options": [{"name": s, "color": "default"} for s in ["Very High","High","Medium","Low"]]}},
            "Status":      {"select": {"options": [{"name": s, "color": "default"} for s in ["Active","Expired","Triggered"]]}},
            "Date":        {"date": {}},
            "Signals":     {"rich_text": {}},
        },
    },
}


def create_database(parent_page_id: str, name: str, config: dict) -> str | None:
    payload = {
        "parent":      {"type": "page_id", "page_id": parent_page_id},
        "title":       [{"type": "text", "text": {"content": name}}],
        "description": [{"type": "text", "text": {"content": config["description"]}}],
        "properties":  config["properties"],
        "is_inline":   False,
    }
    try:
        r = requests.post(
            "https://api.notion.com/v1/databases",
            headers=HEADERS,
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        db_id = r.json()["id"].replace("-", "")
        print(f"  ✓ {name}: {db_id}")
        return db_id
    except Exception as e:
        print(f"  ✗ {name}: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"    {e.response.text[:300]}")
        return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    parent_id = sys.argv[1].strip().replace("-", "")
    print(f"\nCreating Notion databases under page {parent_id}...\n")

    ids = {}
    for name, config in DATABASES.items():
        db_id = create_database(parent_id, name, config)
        ids[name] = db_id

    print("\n" + "="*60)
    print("Add these to /root/bastobot/.env:\n")
    env_keys = {
        "Chain Snapshots": "NOTION_CHAIN_SNAPSHOTS_DB_ID",
        "Trade Monitor":   "NOTION_TRADE_MONITOR_DB_ID",
        "Hot Trades":      "NOTION_HOT_TRADES_DB_ID",
    }
    for name, env_key in env_keys.items():
        val = ids.get(name) or "<failed>"
        print(f"{env_key}={val}")
    print("\nThen restart the scanner:")
    print("  systemctl daemon-reload && systemctl restart bastobot-scanner")


if __name__ == "__main__":
    main()
