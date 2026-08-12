"""
DEX arbitrage opportunity monitor — logs all opportunities to Redis for periodic review.
Tracks both "alert-worthy" (≥1%, ≥$500k) and "watch-list" (0.5%+, lower liquidity) opportunities.
"""

import sys
import json
import redis as _redis_lib
from datetime import datetime, timezone, timedelta
from typing import Optional

sys.path.insert(0, "/root/bastobot")

_r = _redis_lib.Redis(host="localhost", port=6379, db=0)

# Redis keys
_MONITOR_KEY = "dex_monitor:opportunities"          # Sorted set: opportunities by timestamp
_SUMMARY_KEY = "dex_monitor:summary:{date}"         # Daily summary
_ALERT_WORTHY_KEY = "dex_monitor:alert_worthy"      # Just the high-quality ones
_WATCH_LIST_KEY = "dex_monitor:watch_list"          # Lower-threshold opportunities


def log_opportunity(
    symbol: str,
    chain: str,
    dex: str,
    spread_pct: float,
    dex_price: float,
    cex_price: float,
    liquidity: float,
    volume_24h: float,
    is_alert_worthy: bool = False,
) -> None:
    """
    Log an arbitrage opportunity to Redis for monitoring.

    Args:
        is_alert_worthy: True if this triggered an actual alert, False if just watch-list
    """
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()
    date_key = now.date().isoformat()

    opp = {
        "symbol": symbol,
        "chain": chain,
        "dex": dex,
        "spread_pct": spread_pct,
        "dex_price": dex_price,
        "cex_price": cex_price,
        "liquidity": liquidity,
        "volume_24h": volume_24h,
        "timestamp": timestamp,
        "alert_worthy": is_alert_worthy,
    }

    # Add to main monitor log (keep last 1000)
    _r.zadd(_MONITOR_KEY, {json.dumps(opp): now.timestamp()})
    _r.zremrangebyrank(_MONITOR_KEY, 0, -1001)  # Keep only last 1000

    # Add to daily summary
    summary_key = _SUMMARY_KEY.format(date=date_key)
    _r.lpush(summary_key, json.dumps(opp))
    _r.expire(summary_key, 604800)  # Keep 7 days

    # Separate bins for quick access
    if is_alert_worthy:
        _r.lpush(_ALERT_WORTHY_KEY, json.dumps(opp))
        _r.expire(_ALERT_WORTHY_KEY, 86400)  # Keep 24h
    else:
        _r.lpush(_WATCH_LIST_KEY, json.dumps(opp))
        _r.expire(_WATCH_LIST_KEY, 86400)  # Keep 24h


def get_recent_opportunities(limit: int = 50, alert_worthy_only: bool = False) -> list[dict]:
    """Get recent logged opportunities."""
    if alert_worthy_only:
        key = _ALERT_WORTHY_KEY
    else:
        key = _MONITOR_KEY

    if alert_worthy_only:
        raw = _r.lrange(key, 0, limit - 1)
    else:
        raw = _r.zrevrange(key, 0, limit - 1)

    return [json.loads(item) for item in raw if item]


def get_daily_summary(date: Optional[str] = None) -> list[dict]:
    """Get opportunities from a specific date (YYYY-MM-DD). Defaults to today."""
    if date is None:
        date = datetime.now(timezone.utc).date().isoformat()

    key = _SUMMARY_KEY.format(date=date)
    raw = _r.lrange(key, 0, -1)
    return [json.loads(item) for item in raw if item]


def get_statistics(hours: int = 24) -> dict:
    """Get summary statistics from the last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    opportunities = get_recent_opportunities(limit=500)

    stats = {
        "period_hours": hours,
        "total_opps": 0,
        "alert_worthy_count": 0,
        "avg_spread_pct": 0,
        "max_spread_pct": 0,
        "by_chain": {},
        "by_dex": {},
        "by_symbol": {},
    }

    spreads = []
    for opp in opportunities:
        try:
            ts = datetime.fromisoformat(opp["timestamp"])
            if ts < cutoff:
                continue
            stats["total_opps"] += 1
            if opp.get("alert_worthy"):
                stats["alert_worthy_count"] += 1

            spread = abs(opp["spread_pct"])
            spreads.append(spread)
            stats["max_spread_pct"] = max(stats["max_spread_pct"], spread)

            # Aggregate by chain
            chain = opp["chain"]
            if chain not in stats["by_chain"]:
                stats["by_chain"][chain] = {"count": 0, "avg_spread": 0, "total_liq": 0}
            stats["by_chain"][chain]["count"] += 1
            stats["by_chain"][chain]["total_liq"] += opp["liquidity"]

            # Aggregate by dex
            dex = opp["dex"]
            if dex not in stats["by_dex"]:
                stats["by_dex"][dex] = {"count": 0, "avg_spread": 0}
            stats["by_dex"][dex]["count"] += 1

            # Aggregate by symbol
            symbol = opp["symbol"]
            if symbol not in stats["by_symbol"]:
                stats["by_symbol"][symbol] = {"count": 0, "spreads": []}
            stats["by_symbol"][symbol]["count"] += 1
            stats["by_symbol"][symbol]["spreads"].append(spread)

        except Exception:
            continue

    if spreads:
        stats["avg_spread_pct"] = sum(spreads) / len(spreads)

    # Calculate per-chain averages
    for chain_data in stats["by_chain"].values():
        if chain_data["count"] > 0:
            chain_data["total_liq"] = int(chain_data["total_liq"])

    # Calculate per-symbol max spread
    for symbol_data in stats["by_symbol"].values():
        if symbol_data["spreads"]:
            symbol_data["max_spread"] = max(symbol_data["spreads"])
            symbol_data["avg_spread"] = sum(symbol_data["spreads"]) / len(symbol_data["spreads"])
        del symbol_data["spreads"]

    return stats


def format_opportunities_report(opportunities: list[dict], title: str = "DEX Arbitrage Opportunities") -> str:
    """Pretty-print opportunities."""
    if not opportunities:
        return f"{title}: None found.\n"

    lines = [f"\n{'='*80}"]
    lines.append(f"{title}")
    lines.append(f"{'='*80}\n")

    for i, opp in enumerate(opportunities, 1):
        arrow = "🔺" if opp["spread_pct"] > 0 else "🔻"
        marker = "🔥" if opp.get("alert_worthy") else "👀"
        lines.append(
            f"{i:2d}. {marker} {arrow} {opp['symbol']:8s} | "
            f"{opp['dex']:15s} on {opp['chain']:12s} | "
            f"Spread: {opp['spread_pct']:+6.2f}%"
        )
        lines.append(
            f"      DEX ${opp['dex_price']:>12,.8f} | CEX ${opp['cex_price']:>12,.8f} | "
            f"Liq ${opp['liquidity']:>10,.0f} | Vol ${opp['volume_24h']:>10,.0f}"
        )
        lines.append(f"      {opp['timestamp']}")
        lines.append("")

    lines.append(f"{'='*80}\n")
    return "\n".join(lines)


def format_statistics_report(stats: dict) -> str:
    """Pretty-print statistics."""
    lines = [f"\n{'='*80}"]
    lines.append(f"DEX Arbitrage Statistics — Last {stats['period_hours']}h")
    lines.append(f"{'='*80}\n")

    lines.append(f"Total opportunities: {stats['total_opps']}")
    lines.append(f"  Alert-worthy (≥1%, ≥$500k):  {stats['alert_worthy_count']}")
    lines.append(f"  Watch-list (monitor):          {stats['total_opps'] - stats['alert_worthy_count']}")
    lines.append("")

    if stats["total_opps"] > 0:
        lines.append(f"Spread stats:")
        lines.append(f"  Average: {stats['avg_spread_pct']:.2f}%")
        lines.append(f"  Maximum: {stats['max_spread_pct']:.2f}%")
        lines.append("")

    if stats["by_chain"]:
        lines.append(f"By Chain:")
        for chain, data in sorted(stats["by_chain"].items(), key=lambda x: x[1]["count"], reverse=True):
            lines.append(
                f"  {chain:12s}: {data['count']:3d} opps | "
                f"Total Liq: ${data['total_liq']:>12,.0f}"
            )
        lines.append("")

    if stats["by_dex"]:
        lines.append(f"By DEX:")
        for dex, data in sorted(stats["by_dex"].items(), key=lambda x: x[1]["count"], reverse=True):
            lines.append(f"  {dex:20s}: {data['count']:3d} opps")
        lines.append("")

    if stats["by_symbol"]:
        lines.append(f"Top symbols by activity:")
        for symbol, data in sorted(stats["by_symbol"].items(), key=lambda x: x[1]["count"], reverse=True)[:10]:
            lines.append(
                f"  {symbol:8s}: {data['count']:3d} opps | "
                f"Avg spread {data.get('avg_spread', 0):.2f}% | "
                f"Max {data.get('max_spread', 0):.2f}%"
            )

    lines.append(f"\n{'='*80}\n")
    return "\n".join(lines)
