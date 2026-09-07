"""
Query memory — track last query/topic for context and time-decay updates.
Enables "what's the latest" to work intelligently based on time elapsed.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

BRAIN_ROOT = Path(os.environ.get("BASTOBOT_BRAIN_ROOT", "/root/bastobot/brain"))
QUERY_LOG = BRAIN_ROOT / "last_query.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def save_query(prompt: str, category: str, asset: str = None):
    """
    Save the current query to memory.
    Called after every financial query to track context.
    """
    BRAIN_ROOT.mkdir(parents=True, exist_ok=True)
    data = {
        "timestamp": _utc_now().isoformat(),
        "prompt": prompt,
        "category": category,
        "asset": asset or "general",
    }
    QUERY_LOG.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_last_query() -> dict | None:
    """
    Retrieve the last query from memory.
    Returns: {timestamp, prompt, category, asset} or None
    """
    if not QUERY_LOG.exists():
        return None
    try:
        return json.loads(QUERY_LOG.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[QUERY_MEMORY] Error reading last query: {e}")
        return None


def get_time_since_last_query() -> int | None:
    """
    Get minutes elapsed since last query.
    Returns: minutes, or None if no prior query
    """
    last = get_last_query()
    if not last:
        return None
    try:
        last_time = datetime.fromisoformat(last["timestamp"])
        elapsed = _utc_now() - last_time
        return int(elapsed.total_seconds() / 60)
    except Exception as e:
        print(f"[QUERY_MEMORY] Error calculating elapsed time: {e}")
        return None


def should_update_last_topic(query: str) -> tuple[bool, dict | None]:
    """
    Determine if "what's latest" should update the last topic.
    Returns: (should_update, last_query_data)

    Logic:
    - If <12h since last query on same asset → auto-update
    - If >12h → ask for confirmation first
    - If no prior query → ask for clarification
    """
    keywords = ["latest", "what's new", "update", "whats new", "what's the latest"]
    if not any(kw in query.lower() for kw in keywords):
        return False, None

    last = get_last_query()
    if not last:
        return False, None  # No prior query, ask for clarification

    elapsed_mins = get_time_since_last_query()
    if elapsed_mins is None:
        return False, None

    # < 12 hours (720 minutes) → auto-update
    if elapsed_mins < 720:
        return True, last

    # >= 12 hours → ask for confirmation
    return False, last


def format_update_prompt(last_query: dict, elapsed_mins: int) -> str:
    """
    Format a contextual update prompt based on time elapsed.
    """
    elapsed_hours = elapsed_mins / 60
    asset = last_query.get("asset", "general")
    category = last_query.get("category", "unknown")

    if elapsed_hours < 1:
        time_desc = f"{int(elapsed_mins)} minutes ago"
    elif elapsed_hours < 24:
        time_desc = f"{int(elapsed_hours)} hours ago"
    else:
        time_desc = f"{int(elapsed_hours / 24)} days ago"

    if category == "financial":
        return f"Last question about {asset} was {time_desc}. Provide a price/market update on {asset}."
    else:
        return f"Last question was {time_desc}. Continue on that topic or specify a new one?"


def get_context_prompt(original_query: str) -> str | None:
    """
    If user says "what's latest", return a refined prompt.
    Returns: modified prompt, or None if should ask for clarification
    """
    should_update, last = should_update_last_topic(original_query)

    if should_update:
        # Auto-update the last topic
        elapsed = get_time_since_last_query()
        return format_update_prompt(last, elapsed)

    if last and not should_update:
        # >12h elapsed, ask for confirmation
        asset = last.get("asset", "general")
        return f"Your last query was about {asset} ({get_time_since_last_query() // 60} hours ago). Continue with that, or ask something new?"

    # No prior query
    return None
