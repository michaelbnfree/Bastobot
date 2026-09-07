"""
Barry's persistent brain — file-based markdown vault for interconnected knowledge.
Stores trades, watchlist context, patterns, market analysis, and learnings.
"""

import re
import os
from datetime import datetime, timezone
from pathlib import Path

BRAIN_ROOT = Path(os.environ.get("BASTOBOT_BRAIN_ROOT", "/root/bastobot/brain"))
BRAIN_SUBDIRS = ("trades", "watchlist", "patterns", "market", "learnings")


def ensure_brain_dirs() -> None:
    """Create the brain vault directories explicitly before reads/writes."""
    BRAIN_ROOT.mkdir(parents=True, exist_ok=True)
    for subdir in BRAIN_SUBDIRS:
        (BRAIN_ROOT / subdir).mkdir(exist_ok=True)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return slug.strip("_") or "note"


def _risk_reward(direction: str, entry: float, target: float, sl: float) -> float | None:
    risk = abs(entry - sl)
    if risk <= 0:
        return None

    side = direction.strip().lower()
    if side == "long":
        reward = target - entry
    elif side == "short":
        reward = entry - target
    else:
        reward = abs(target - entry)

    if reward <= 0:
        return None
    return reward / risk


def write_trade_note(symbol: str, direction: str, entry: float, tp1: float, tp2: float, sl: float,
                     horizon: str = "day", conviction: float = 0, notes: str = "") -> str:
    """
    Write a trade setup to the brain.
    Returns: path to written file
    """
    ensure_brain_dirs()
    now = _utc_now()
    timestamp = now.strftime("%Y-%m-%d_%H%M%S")
    filename = f"{timestamp}_{_safe_slug(symbol.upper())}_{_safe_slug(direction.upper())}.md"
    filepath = BRAIN_ROOT / "trades" / filename
    rr = _risk_reward(direction, entry, tp2 if tp2 is not None else tp1, sl)
    rr_text = f"1:{rr:.2f}" if rr is not None else "N/A"
    tp2_text = f"${tp2:,.2f}" if tp2 is not None else "N/A"

    content = f"""# {symbol} {direction.upper()} — {horizon}

**Setup Date:** {now.strftime('%Y-%m-%d %H:%M UTC')}

## Entry & Targets
- **Entry:** ${entry:,.2f}
- **TP1:** ${tp1:,.2f}
- **TP2:** {tp2_text}
- **SL:** ${sl:,.2f}
- **Risk/Reward:** {rr_text} ({'TP2' if tp2 is not None else 'TP1'})

## Context
- **Horizon:** {horizon}
- **Conviction:** {conviction}/10
- **Notes:** {notes or "N/A"}

## Market Condition
*[To be filled by Barry after setup]*

## Outcome
*[Pending]*

---
*Linked patterns & context:*
"""
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


def write_watchlist_note(symbol: str, narrative: str, catalysts: str = "", timeframe: str = "swing") -> str:
    """
    Write/update a watchlist item with context.
    """
    ensure_brain_dirs()
    filepath = BRAIN_ROOT / "watchlist" / f"{_safe_slug(symbol.upper())}.md"

    content = f"""# {symbol}

**Added:** {_utc_now().strftime('%Y-%m-%d')}

## Narrative
{narrative}

## Catalysts
{catalysts or "- TBD"}

## Timeframe
{timeframe}

## Price History
| Date | Price | RSI | Conviction |
|------|-------|-----|------------|
| | | | |

## Related Trades
*None yet*

## Learnings
*Updated as trades execute*

---
"""
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


def write_pattern_note(pattern_name: str, conditions: str, win_rate: float = 0, examples: str = "") -> str:
    """
    Record a trading pattern and its performance.
    """
    ensure_brain_dirs()
    filename = _safe_slug(pattern_name.lower().replace(" ", "_")) + ".md"
    filepath = BRAIN_ROOT / "patterns" / filename

    content = f"""# {pattern_name}

**First Observed:** {_utc_now().strftime('%Y-%m-%d')}

## Conditions
{conditions}

## Performance
- **Win Rate:** {win_rate * 100:.1f}% (0 trades so far)
- **Avg TP Hit:** N/A
- **Avg SL Hit:** N/A

## Examples
{examples or "- TBD"}

## Refinements
*Update as pattern evolves*

---
"""
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


def write_market_snapshot(title: str, content: str) -> str:
    """
    Write market analysis/macro thesis.
    """
    ensure_brain_dirs()
    timestamp = _utc_now().strftime("%Y-%m-%d")
    filename = f"{timestamp}_{_safe_slug(title.lower().replace(' ', '_'))}.md"
    filepath = BRAIN_ROOT / "market" / filename

    full_content = f"""# {title}

**Date:** {timestamp}

{content}

---
"""
    filepath.write_text(full_content, encoding="utf-8")
    return str(filepath)


def write_learning(lesson: str, context: str = "") -> str:
    """
    Record a learning or false signal.
    """
    ensure_brain_dirs()
    now = _utc_now()
    timestamp = now.strftime("%Y-%m-%d_%H%M%S")
    filename = f"{timestamp}_learning.md"
    filepath = BRAIN_ROOT / "learnings" / filename

    content = f"""# Learning

**Date:** {now.strftime('%Y-%m-%d %H:%M UTC')}

## Lesson
{lesson}

## Context
{context or "N/A"}

---
"""
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


def read_watchlist() -> dict:
    """
    Read all watchlist items with context.
    Returns: {symbol: content}
    """
    watchlist = {}
    watchlist_dir = BRAIN_ROOT / "watchlist"
    if watchlist_dir.exists():
        for file in watchlist_dir.glob("*.md"):
            symbol = file.stem.upper()
            watchlist[symbol] = file.read_text(encoding="utf-8")
    return watchlist


def read_patterns() -> dict:
    """
    Read all recorded patterns.
    Returns: {pattern_name: content}
    """
    patterns = {}
    patterns_dir = BRAIN_ROOT / "patterns"
    if patterns_dir.exists():
        for file in patterns_dir.glob("*.md"):
            pattern_name = file.stem
            patterns[pattern_name] = file.read_text(encoding="utf-8")
    return patterns


def search_brain(query: str, max_results: int = 5) -> list:
    """
    Search brain for relevant notes.
    Returns: list of (filepath, excerpt)
    """
    results = []
    query_lower = query.lower()

    if not query_lower:
        return results

    for filepath in BRAIN_ROOT.rglob("*.md"):
        content = filepath.read_text(encoding="utf-8")
        content_lower = content.lower()
        if query_lower in content_lower:
            # Extract excerpt around match
            idx = content_lower.find(query_lower)
            excerpt = content[max(0, idx - 100):min(len(content), idx + 100)]
            results.append((str(filepath), excerpt.strip()))

    return results[:max_results]


def get_brain_context(symbol: str = None) -> str:
    """
    Inject brain context into Barry's prompts.
    If symbol given, return watchlist + related patterns.
    Otherwise, return recent trades + market view.
    """
    context_parts = []

    if symbol:
        # Get watchlist context
        watchlist = read_watchlist()
        if symbol in watchlist:
            context_parts.append(f"## {symbol} Watchlist Context\n{watchlist[symbol]}\n")

    # Get recent trades (last 5)
    trades_dir = BRAIN_ROOT / "trades"
    if trades_dir.exists():
        recent_trades = sorted(trades_dir.glob("*.md"), reverse=True)[:5]
        if recent_trades:
            context_parts.append("## Recent Trades\n")
            for trade_file in recent_trades:
                context_parts.append(f"- {trade_file.stem}\n")

    # Get patterns summary
    patterns = read_patterns()
    if patterns:
        context_parts.append("## Learned Patterns\n")
        for pattern_name in list(patterns.keys())[:3]:
            context_parts.append(f"- {pattern_name}\n")

    return "\n".join(context_parts) if context_parts else ""


def export_brain_summary() -> dict:
    """
    Export brain state as JSON for review.
    """
    ensure_brain_dirs()
    summary = {
        "updated": _utc_now().isoformat(),
        "trades": len(list((BRAIN_ROOT / "trades").glob("*.md"))),
        "watchlist": len(list((BRAIN_ROOT / "watchlist").glob("*.md"))),
        "patterns": len(list((BRAIN_ROOT / "patterns").glob("*.md"))),
        "market_notes": len(list((BRAIN_ROOT / "market").glob("*.md"))),
        "learnings": len(list((BRAIN_ROOT / "learnings").glob("*.md"))),
    }
    return summary
