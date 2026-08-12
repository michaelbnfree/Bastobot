"""
Logs high-gain DEX/CEX arbitrage opportunities to Notion database.
Builds dataset for 3-month analysis and strategy refinement.

Setup:
  1. Create a Notion database with columns: Date, Symbol, Chain, DEX, Spread %,
     CEX Price, DEX Price, Liquidity, Volume 24h, Status, Notes
  2. Set DATABASE_ID and NOTION_API_KEY in .env
"""

import os
import requests
from datetime import datetime, timezone

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_VERSION = "2022-06-28"
# Set this to your DEX Arbitrage Opportunities database ID
DATABASE_ID = os.getenv("NOTION_DEX_DATABASE_ID", "")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}


def log_arbitrage_opportunity(
    symbol: str,
    chain: str,
    dex: str,
    spread_pct: float,
    dex_price: float,
    cex_price: float,
    liquidity: float,
    volume_24h: float,
    notes: str = "",
) -> bool:
    """
    Log an arbitrage opportunity to Notion.
    Returns True if successful, False otherwise.
    """
    if not NOTION_API_KEY or not DATABASE_ID:
        print("[NOTION] Missing NOTION_API_KEY or NOTION_DEX_DATABASE_ID")
        return False

    try:
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        # Determine status based on spread
        if abs(spread_pct) >= 1.5:
            status = "High Priority"
        elif abs(spread_pct) >= 1.0:
            status = "Active"
        else:
            status = "Monitor"

        properties = {
            "Date": {"date": {"start": today}},
            "Symbol": {"title": [{"text": {"content": symbol}}]},
            "Chain": {"select": {"name": chain}},
            "DEX": {"rich_text": [{"text": {"content": dex}}]},
            "Spread %": {"number": round(spread_pct, 2)},
            "CEX Price": {"number": round(cex_price, 8)},
            "DEX Price": {"number": round(dex_price, 8)},
            "Liquidity": {"number": int(liquidity)},
            "Volume 24h": {"number": int(volume_24h)},
            "Status": {"select": {"name": status}},
            "Direction": {"select": {"name": "SELL on DEX" if spread_pct > 0 else "BUY on DEX"}},
            "Timestamp": {"rich_text": [{"text": {"content": now.isoformat()}}]},
        }

        if notes:
            properties["Notes"] = {"rich_text": [{"text": {"content": notes}}]}

        payload = {
            "parent": {"database_id": DATABASE_ID},
            "properties": properties,
        }

        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers=HEADERS,
            json=payload,
            timeout=10,
        )
        r.raise_for_status()
        print(f"[NOTION] Logged {symbol} {spread_pct:+.2f}% on {dex}")
        return True

    except Exception as e:
        print(f"[NOTION] Log failed: {e}")
        return False


def get_opportunity_summary(days: int = 7) -> dict:
    """
    Query Notion database for opportunities from the last N days.
    Returns stats if database is accessible.
    """
    if not NOTION_API_KEY or not DATABASE_ID:
        return {"error": "Missing credentials"}

    try:
        # Query database with date filter
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

        payload = {
            "filter": {
                "property": "Date",
                "date": {"on_or_after": cutoff},
            },
        }

        r = requests.post(
            f"https://api.notion.com/v1/databases/{DATABASE_ID}/query",
            headers=HEADERS,
            json=payload,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        results = data.get("results", [])
        if not results:
            return {
                "days": days,
                "count": 0,
                "message": "No opportunities logged yet",
            }

        # Summarize
        spreads = []
        symbols = {}
        chains = {}
        dexes = {}

        for page in results:
            props = page.get("properties", {})
            try:
                spread = props.get("Spread %", {}).get("number", 0)
                symbol = props.get("Symbol", {}).get("title", [{}])[0].get("text", {}).get("content", "?")
                chain = props.get("Chain", {}).get("select", {}).get("name", "?")
                dex = props.get("DEX", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "?")

                if spread:
                    spreads.append(abs(spread))
                symbols[symbol] = symbols.get(symbol, 0) + 1
                chains[chain] = chains.get(chain, 0) + 1
                dexes[dex] = dexes.get(dex, 0) + 1
            except:
                pass

        summary = {
            "days": days,
            "count": len(results),
            "avg_spread": sum(spreads) / len(spreads) if spreads else 0,
            "max_spread": max(spreads) if spreads else 0,
            "by_symbol": symbols,
            "by_chain": chains,
            "by_dex": dexes,
        }

        return summary

    except Exception as e:
        return {"error": str(e)}
