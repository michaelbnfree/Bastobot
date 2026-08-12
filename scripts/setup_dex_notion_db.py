#!/usr/bin/env python3
"""
Setup script to create the DEX Arbitrage Opportunities database in Notion.
Must have NOTION_API_KEY set in .env before running.

Usage:
  python scripts/setup_dex_notion_db.py

This creates a new database with all required columns and prints the database ID
to add to your .env as NOTION_DEX_DATABASE_ID.
"""

import os
import sys
import requests
import json
from datetime import datetime, timezone

# Load .env
from dotenv import load_dotenv
load_dotenv("/root/bastobot/.env")

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_VERSION = "2022-06-28"

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}


def create_database():
    """Create DEX Arbitrage Opportunities database."""
    if not NOTION_API_KEY:
        print("❌ NOTION_API_KEY not found in .env")
        sys.exit(1)

    print("🚀 Creating DEX Arbitrage Opportunities database...")

    # Parent should be a Notion page/workspace where user has access
    # We'll try to create in root, or ask for a parent page ID
    payload = {
        "parent": {"type": "workspace", "workspace": True},
        "title": [{"text": {"content": "DEX Arbitrage Opportunities (3-Month Dataset)"}}],
        "properties": {
            "Date": {
                "date": {}
            },
            "Symbol": {
                "title": {}
            },
            "Chain": {
                "select": {
                    "options": [
                        {"name": "ethereum", "color": "blue"},
                        {"name": "solana", "color": "green"},
                        {"name": "arbitrum", "color": "purple"},
                        {"name": "polygon", "color": "pink"},
                        {"name": "base", "color": "orange"},
                        {"name": "optimism", "color": "red"},
                        {"name": "binance", "color": "yellow"},
                    ]
                }
            },
            "DEX": {
                "rich_text": {}
            },
            "Spread %": {
                "number": {"format": "percent"}
            },
            "CEX Price": {
                "number": {"format": "dollar"}
            },
            "DEX Price": {
                "number": {"format": "dollar"}
            },
            "Liquidity": {
                "number": {"format": "dollar"}
            },
            "Volume 24h": {
                "number": {"format": "dollar"}
            },
            "Status": {
                "select": {
                    "options": [
                        {"name": "High Priority", "color": "red"},
                        {"name": "Active", "color": "orange"},
                        {"name": "Monitor", "color": "yellow"},
                        {"name": "Logged", "color": "green"},
                        {"name": "Executed", "color": "blue"},
                    ]
                }
            },
            "Direction": {
                "select": {
                    "options": [
                        {"name": "SELL on DEX", "color": "red"},
                        {"name": "BUY on DEX", "color": "green"},
                    ]
                }
            },
            "Notes": {
                "rich_text": {}
            },
            "Timestamp": {
                "rich_text": {}
            },
        }
    }

    try:
        r = requests.post(
            "https://api.notion.com/v1/databases",
            headers=HEADERS,
            json=payload,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        db_id = data.get("id", "").replace("-", "")
        url = data.get("url", "")

        print("\n✅ Database created successfully!")
        print(f"\n📋 Database ID: {db_id}")
        print(f"🔗 URL: {url}")
        print("\n📝 Add this to your .env file:")
        print(f"NOTION_DEX_DATABASE_ID={db_id}")
        print("\n✨ Then reload BastoBot to start logging opportunities.")

        return db_id

    except Exception as e:
        print(f"❌ Failed to create database: {e}")
        if hasattr(e, "response"):
            try:
                print(f"Response: {e.response.json()}")
            except:
                print(f"Response: {e.response.text}")
        sys.exit(1)


def check_existing():
    """Check if database already configured."""
    db_id = os.getenv("NOTION_DEX_DATABASE_ID")
    if db_id:
        print(f"✅ Database already configured: {db_id}")
        print("No action needed.")
        return True
    return False


if __name__ == "__main__":
    if check_existing():
        sys.exit(0)

    create_database()
