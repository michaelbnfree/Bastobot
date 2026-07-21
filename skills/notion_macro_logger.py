#!/usr/bin/env python3
"""
Logs Barry's macro analysis and trend monitoring to Notion.
Runs after each analysis cycle (every 10 minutes).
"""

import os
import json
import requests
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_VERSION = "2022-06-28"
DATABASE_ID = os.getenv("NOTION_MACRO_DB_ID")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}


def log_macro_analysis_to_notion(macro_data: dict, trend_data: dict) -> str | None:
    """
    Log macro and trend analysis to Notion database.

    Args:
        macro_data: Output from macro_monitor.analyze()
        trend_data: Output from trend_monitor.analyze()

    Returns:
        Notion page URL or None if logging failed
    """
    if not NOTION_API_KEY or not DATABASE_ID:
        logger.warning("Notion credentials not configured for macro analysis logging")
        return None

    try:
        # Extract data
        timestamp = macro_data.get('timestamp', datetime.now(timezone.utc).isoformat())
        regime = macro_data.get('market_regime', {})
        volatility = macro_data.get('volatility', {})
        sentiment = macro_data.get('sentiment', {})
        alignment = trend_data.get('alignment', {})
        timeframes = trend_data.get('trends', {})

        # Build Notion page
        payload = {
            "parent": {"database_id": DATABASE_ID},
            "properties": {
                "Name": {
                    "title": [
                        {
                            "text": {
                                "content": f"Analysis - {timestamp.split('T')[0]}"
                            }
                        }
                    ]
                },
                "Timestamp": {
                    "date": {
                        "start": timestamp.split('T')[0]
                    }
                },
                "Market Regime": {
                    "select": {
                        "name": regime.get('regime', 'Unknown')
                    }
                },
                "Regime Confidence": {
                    "number": regime.get('confidence', 0) * 100
                },
                "Volatility": {
                    "select": {
                        "name": volatility.get('regime', 'Unknown')
                    }
                },
                "Sentiment": {
                    "select": {
                        "name": sentiment.get('sentiment', 'Unknown')
                    }
                },
                "Sentiment Score": {
                    "number": sentiment.get('score', 0)
                },
                "Trend Alignment": {
                    "select": {
                        "name": alignment.get('alignment', 'Unknown')
                    }
                },
                "Alignment Confidence": {
                    "number": alignment.get('confidence', 0) * 100
                },
                "1h Trend": {
                    "select": {
                        "name": timeframes.get('1h', {}).get('direction', 'Unknown')
                    }
                },
                "4h Trend": {
                    "select": {
                        "name": timeframes.get('4h', {}).get('direction', 'Unknown')
                    }
                },
                "1d Trend": {
                    "select": {
                        "name": timeframes.get('1d', {}).get('direction', 'Unknown')
                    }
                },
                "Summary": {
                    "rich_text": [
                        {
                            "text": {
                                "content": macro_data.get('summary', '')[:2000]
                            }
                        }
                    ]
                },
                "Trend Summary": {
                    "rich_text": [
                        {
                            "text": {
                                "content": trend_data.get('summary', '')[:2000]
                            }
                        }
                    ]
                }
            }
        }

        # Create page
        response = requests.post(
            "https://api.notion.com/v1/pages",
            headers=HEADERS,
            json=payload,
            timeout=10
        )

        if response.status_code == 200:
            page_id = response.json()['id']
            page_url = f"https://notion.so/{page_id.replace('-', '')}"
            logger.info(f"Logged macro analysis to Notion: {page_url}")
            return page_url
        else:
            logger.error(f"Notion API error: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        logger.error(f"Failed to log macro analysis to Notion: {e}")
        return None


if __name__ == '__main__':
    # Test logging
    test_macro = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'market_regime': {'regime': 'BULL', 'confidence': 0.85},
        'volatility': {'regime': 'NORMAL', 'volatility_pct': 5.0},
        'sentiment': {'sentiment': 'OPTIMISTIC', 'score': 60.2},
        'summary': 'BULL market with NORMAL volatility. Optimistic sentiment'
    }

    test_trend = {
        'alignment': {'alignment': 'MIXED_BULLISH', 'confidence': 0.6},
        'trends': {
            '1h': {'direction': 'UP'},
            '4h': {'direction': 'CONSOLIDATING'},
            '1d': {'direction': 'CONSOLIDATING'}
        },
        'summary': 'Mixed bullish alignment - 1h strong, 4h/1d consolidating'
    }

    result = log_macro_analysis_to_notion(test_macro, test_trend)
    print(f"Result: {result}")
