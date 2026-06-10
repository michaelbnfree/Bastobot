"""
Watchlist manager for the coin scanner.
5 user-defined slots + 3 auto-scanned slots, stored in Redis.
"""

import json
import redis as _redis_lib
from datetime import datetime, timezone

_r = _redis_lib.Redis(host="localhost", port=6379, db=0)

USER_KEY = "watchlist:user"
AUTO_KEY = "watchlist:auto"
MAX_USER = 5
MAX_AUTO = 3


def _load(key: str) -> list:
    raw = _r.get(key)
    return json.loads(raw) if raw else []


def _save(key: str, data: list) -> None:
    _r.set(key, json.dumps(data))


def add_user(symbol: str, narrative: str = "") -> tuple[bool, str]:
    sym   = symbol.upper()
    items = _load(USER_KEY)
    if any(x["symbol"] == sym for x in items):
        return False, f"{sym} is already on your watchlist."
    if len(items) >= MAX_USER:
        return False, f"Watchlist full ({MAX_USER} user slots). Remove a coin first."
    items.append({
        "symbol":    sym,
        "narrative": narrative.strip(),
        "added":     datetime.now(timezone.utc).isoformat(),
    })
    _save(USER_KEY, items)
    nar_note = f" — {narrative.strip()}" if narrative.strip() else ""
    return True, f"Added {sym} to watchlist{nar_note}."


def remove_user(symbol: str) -> tuple[bool, str]:
    sym    = symbol.upper()
    items  = _load(USER_KEY)
    before = len(items)
    items  = [x for x in items if x["symbol"] != sym]
    if len(items) == before:
        return False, f"{sym} not found in your watchlist."
    _save(USER_KEY, items)
    return True, f"Removed {sym} from watchlist."


def update_narrative(symbol: str, narrative: str) -> tuple[bool, str]:
    sym   = symbol.upper()
    items = _load(USER_KEY)
    for item in items:
        if item["symbol"] == sym:
            item["narrative"] = narrative.strip()
            _save(USER_KEY, items)
            return True, f"Updated {sym} narrative."
    return False, f"{sym} not found in your watchlist."


def set_auto(entries: list[dict]) -> None:
    """Called by conviction engine to update the 3 auto-scanned slots."""
    _save(AUTO_KEY, entries[:MAX_AUTO])


def get_user() -> list[dict]:
    return _load(USER_KEY)


def get_auto() -> list[dict]:
    return _load(AUTO_KEY)


def get_all_symbols() -> list[str]:
    """All symbols currently being watched — user + auto, BTC always included."""
    user = {x["symbol"] for x in _load(USER_KEY)}
    auto = {x["symbol"] for x in _load(AUTO_KEY)}
    combined = list(user | auto)
    if "BTC" not in combined:
        combined.insert(0, "BTC")
    return combined


def format_watchlist() -> str:
    user = _load(USER_KEY)
    auto = _load(AUTO_KEY)
    lines = ["📋 *Watchlist*\n"]

    lines.append(f"*User slots ({len(user)}/{MAX_USER}):*")
    if user:
        for item in user:
            nar = f"\n    _{item['narrative']}_" if item.get("narrative") else ""
            lines.append(f"  • *{item['symbol']}*{nar}")
    else:
        lines.append("  (empty — add up to 5: `watch <COIN>` or `watch <COIN> - <narrative>`)")

    lines.append(f"\n*Auto-scanned ({len(auto)}/{MAX_AUTO}):*")
    if auto:
        for item in auto:
            score_str = f" [{item.get('score', '?')}/10]"
            dir_str   = f" {item.get('direction', '').capitalize()}" if item.get("direction") else ""
            lines.append(f"  • *{item['symbol']}*{score_str}{dir_str}")
    else:
        lines.append("  (filled automatically by the scanner)")

    return "\n".join(lines)
