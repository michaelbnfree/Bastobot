#!/usr/bin/env python3
"""
DEX Monitor Report — view logged arbitrage opportunities and statistics.

Usage:
  python dex_monitor_report.py alert       # Show recent alert-worthy opportunities
  python dex_monitor_report.py watch       # Show recent watch-list opportunities
  python dex_monitor_report.py stats [24]  # Show statistics (default 24h)
  python dex_monitor_report.py daily       # Show today's opportunities
"""

import sys
import argparse

sys.path.insert(0, "/root/bastobot")

from skills.dex_monitor import (
    get_recent_opportunities,
    get_daily_summary,
    get_statistics,
    format_opportunities_report,
    format_statistics_report,
)


def cmd_alert(args):
    """Show recent alert-worthy opportunities."""
    opps = get_recent_opportunities(limit=args.limit, alert_worthy_only=True)
    print(format_opportunities_report(opps, title="🔥 Alert-Worthy Opportunities (≥1%, ≥$500k)"))
    print(f"Total: {len(opps)} opportunities\n")


def cmd_watch(args):
    """Show recent watch-list opportunities."""
    all_opps = get_recent_opportunities(limit=args.limit)
    watch_opps = [o for o in all_opps if not o.get("alert_worthy")]
    print(format_opportunities_report(watch_opps, title="👀 Watch-List Opportunities (0.5%+, monitor only)"))
    print(f"Total: {len(watch_opps)} opportunities\n")


def cmd_stats(args):
    """Show statistics."""
    stats = get_statistics(hours=args.hours)
    print(format_statistics_report(stats))


def cmd_daily(args):
    """Show today's opportunities."""
    opps = get_daily_summary()
    print(format_opportunities_report(opps, title="📊 Today's Opportunities"))
    print(f"Total: {len(opps)} opportunities\n")


def main():
    parser = argparse.ArgumentParser(
        description="DEX Monitor Report — view logged arbitrage opportunities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  dex_monitor_report.py alert              Show recent alert-worthy opportunities
  dex_monitor_report.py watch              Show recent watch-list opportunities
  dex_monitor_report.py stats 48           Show last 48 hours of stats
  dex_monitor_report.py daily              Show today's opportunities
        """
    )

    parser.add_argument("command", choices=["alert", "watch", "stats", "daily"],
                        help="Report type")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max opportunities to show (default 50)")
    parser.add_argument("--hours", type=int, default=24,
                        help="Hours to include in stats (default 24)")

    args = parser.parse_args()

    commands = {
        "alert": cmd_alert,
        "watch": cmd_watch,
        "stats": cmd_stats,
        "daily": cmd_daily,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
