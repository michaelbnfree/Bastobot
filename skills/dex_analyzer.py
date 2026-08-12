"""
DEX price analyzer — convenience wrapper for DexScreener integration.
Generates comparison reports, finds arbitrage opportunities, and displays multi-chain liquidity.
"""

import sys
sys.path.insert(0, "/root/bastobot")

from skills.dexscreener_client import DexScreenerClient
from datetime import datetime, timezone
from typing import Optional


def get_dex_report(symbol: str, cex_price: Optional[float] = None) -> dict:
    """
    Generate a comprehensive DEX analysis report for a symbol.

    Args:
        symbol: Token symbol (e.g., "ETH", "SOL", "BTC")
        cex_price: Optional CEX price to compare against (from Binance)

    Returns:
        dict with price data, liquidity, and arbitrage analysis
    """
    client = DexScreenerClient()

    report = {
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dex_prices": {},
        "best_price": None,
        "cex_comparison": None,
    }

    # Fetch DEX prices across all chains
    dex_data = client.get_dex_prices(symbol)
    report["dex_prices"] = dex_data

    # Get best price
    best = client.get_best_price(symbol)
    if best:
        report["best_price"] = best

    # Compare to CEX if provided
    if cex_price:
        report["cex_comparison"] = client.compare_dex_cex_prices(symbol, cex_price)

    return report


def find_arbitrage_opportunities(symbol: str, cex_price: float, threshold: float = 0.5, min_liquidity: float = 500000) -> list[dict]:
    """
    Find all DEX/CEX arbitrage opportunities above threshold.

    Args:
        symbol: Token symbol
        cex_price: CEX price (e.g., Binance)
        threshold: Min % spread to report (default 0.5%)
        min_liquidity: Min liquidity required to execute (default $500k to avoid slippage)

    Returns:
        list of opportunities sorted by spread (highest first)
    """
    client = DexScreenerClient()
    dex_data = client.get_dex_prices(symbol)

    opportunities = []

    for chain, dexes in dex_data.items():
        for dex_name, price_info in dexes.items():
            price = price_info.get("price")
            liquidity = price_info.get("liquidity", 0)
            if not price or liquidity < min_liquidity:
                continue

            spread_pct = ((price - cex_price) / cex_price) * 100

            if abs(spread_pct) >= threshold:
                opp = {
                    "symbol": symbol,
                    "chain": chain,
                    "dex": dex_name,
                    "dex_price": price,
                    "cex_price": cex_price,
                    "spread_pct": spread_pct,
                    "direction": "SELL on DEX" if spread_pct > 0 else "BUY on DEX",
                    "liquidity": liquidity,
                    "volume_24h": price_info.get("volume_24h", 0),
                }
                opportunities.append(opp)

    # Sort by absolute spread (highest first)
    opportunities.sort(key=lambda x: abs(x["spread_pct"]), reverse=True)
    return opportunities


def format_dex_report(report: dict) -> str:
    """Pretty-print a DEX report."""
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"DEX Analysis: {report['symbol']}")
    lines.append(f"{'='*60}")

    if report.get("best_price"):
        bp = report["best_price"]
        lines.append(f"\n🥇 BEST PRICE:")
        lines.append(f"  Chain:     {bp['chain'].upper()}")
        lines.append(f"  DEX:       {bp['dex']}")
        lines.append(f"  Price:     ${bp['price']:,.8f}")
        lines.append(f"  Liquidity: ${bp['liquidity']:,.0f}")

    if report.get("cex_comparison"):
        comp = report["cex_comparison"]
        lines.append(f"\n💱 CEX/DEX COMPARISON:")
        lines.append(f"  CEX Price: ${comp['cex_price']:,.8f}")
        if comp.get("dex_best"):
            db = comp["dex_best"]
            lines.append(f"  DEX Price: ${db['price']:,.8f} ({db['dex']} on {db['chain']})")
            lines.append(f"  Spread:    {comp['arbitrage_pct']:+.2f}%")

    if report.get("dex_prices"):
        lines.append(f"\n📊 ALL DEX PRICES BY CHAIN:")
        for chain, dexes in report["dex_prices"].items():
            lines.append(f"\n  {chain.upper()}:")
            for dex_name, price_info in dexes.items():
                lines.append(
                    f"    {dex_name:20s} ${price_info.get('price', 0):>12,.8f} "
                    f"(Liq: ${price_info.get('liquidity', 0):>12,.0f})"
                )

    lines.append(f"\n{'='*60}\n")
    return "\n".join(lines)


def format_opportunities(opportunities: list[dict]) -> str:
    """Pretty-print arbitrage opportunities."""
    if not opportunities:
        return "No arbitrage opportunities found.\n"

    lines = []
    lines.append(f"{'='*70}")
    lines.append(f"ARBITRAGE OPPORTUNITIES (sorted by spread)")
    lines.append(f"{'='*70}\n")

    for i, opp in enumerate(opportunities, 1):
        arrow = "🔺" if opp["spread_pct"] > 0 else "🔻"
        lines.append(
            f"{i}. {arrow} {opp['symbol']} on {opp['dex'].upper():<15} ({opp['chain']})"
        )
        lines.append(
            f"   {opp['direction']}: {opp['spread_pct']:+.2f}%"
        )
        lines.append(
            f"   DEX ${opp['dex_price']:,.8f} vs CEX ${opp['cex_price']:,.8f}"
        )
        lines.append(
            f"   Liquidity: ${opp['liquidity']:,.0f} | Vol 24h: ${opp['volume_24h']:,.0f}"
        )
        lines.append("")

    lines.append(f"{'='*70}\n")
    return "\n".join(lines)
