"""
DexScreener API client for fetching DEX liquidity pool data across chains.
Aggregates prices from Uniswap, SushiSwap, Jupiter, Orca, Meteora, and other DEXes.

Chains supported:
  - ethereum (Uniswap, SushiSwap)
  - solana (Jupiter, Orca, Meteora, Marinade)
  - arbitrum (Uniswap, SushiSwap)
  - polygon (Uniswap, SushiSwap)
  - base (Uniswap)
  - optimism (Uniswap)
  - binance (PanCakeSwap)
"""

import requests
import json
from typing import Optional
from datetime import datetime, timezone

BASE_URL = "https://api.dexscreener.com/latest"
TIMEOUT = 10

# Token address mappings by chain (commonly tracked assets)
TOKEN_ADDRESSES = {
    "ethereum": {
        "ETH": "0x",  # Native token
        "USDC": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        "USDT": "0xdac17f958d2ee523a2206206994597c13d831ec7",
    },
    "solana": {
        "SOL": "So11111111111111111111111111111111111111112",
        "USDC": "EPjFWaJsxqwj46Pi64a5rqaXbE98nrGQX7bgD5d3xfP9",
        "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BcWNc",
    },
    "arbitrum": {
        "ARB": "0x912ce59144191c1204e64559fe8253a0e9b7edd7",
        "ETH": "0x",  # Native
        "USDC": "0xaf88d065e77c8cc2239327c5edb3a432268e5831",
        "USDT": "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9",
    },
    "polygon": {
        "MATIC": "0x",  # Native
        "USDC": "0x2791bca1f2de4661ed88a30c99a7a9449aa84174",
        "USDT": "0xc2132d05d31c914a87c6611c10748aeb04b58e8f",
    },
}

# Chain IDs for DexScreener API
CHAIN_IDS = {
    "ethereum": "ethereum",
    "solana": "solana",
    "arbitrum": "arbitrum",
    "polygon": "polygon",
    "base": "base",
    "optimism": "optimism",
    "binance": "bsc",
}


class DexScreenerClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.timeout = TIMEOUT

    def _search_token(self, symbol: str, chain: str = "ethereum") -> Optional[dict]:
        """Search for a token by symbol. Returns first matching pair."""
        try:
            resp = self.session.get(
                f"{BASE_URL}/dex/search",
                params={"q": symbol},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs", [])

            # Filter to requested chain if specified
            if chain and pairs:
                pairs = [p for p in pairs if p.get("chainId") == CHAIN_IDS.get(chain, chain)]

            if pairs:
                return pairs[0]  # Return highest liquidity match
            return None
        except Exception as e:
            print(f"[DEX] search_token({symbol}) failed: {e}")
            return None

    def _get_pair_by_address(self, chain: str, pair_address: str) -> Optional[dict]:
        """Get pair data by chain and address."""
        try:
            chain_id = CHAIN_IDS.get(chain, chain)
            resp = self.session.get(
                f"{BASE_URL}/dex/pairs/{chain_id}/{pair_address}",
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            pair = data.get("pair")
            return pair
        except Exception as e:
            print(f"[DEX] get_pair({chain}/{pair_address}) failed: {e}")
            return None

    def get_dex_prices(self, symbol: str, chains: Optional[list[str]] = None) -> dict:
        """
        Get DEX prices for a token across multiple chains.
        Returns: {chain: {dex: price, liquidity, volume_24h, ...}}
        """
        if chains is None:
            chains = list(CHAIN_IDS.keys())

        result = {}

        for chain in chains:
            try:
                pair = self._search_token(symbol, chain)
                if not pair:
                    continue

                # Extract relevant data
                dex_name = pair.get("dexId", "unknown")
                chain_id = pair.get("chainId", chain)

                price_data = {
                    "price": float(pair.get("priceUsd", 0)) if pair.get("priceUsd") else None,
                    "liquidity": float(pair.get("liquidity", {}).get("usd", 0)),
                    "volume_24h": float(pair.get("volume", {}).get("h24", 0)),
                    "market_cap": float(pair.get("marketCap", 0)) if pair.get("marketCap") else None,
                    "dex": dex_name,
                    "pair_address": pair.get("pairAddress"),
                    "base_token": pair.get("baseToken", {}).get("symbol"),
                    "quote_token": pair.get("quoteToken", {}).get("symbol"),
                }

                # Add price change data if available
                if "priceChange" in pair:
                    price_data["price_change_24h_pct"] = float(pair["priceChange"].get("h24", 0))
                    price_data["price_change_6h_pct"] = float(pair["priceChange"].get("h6", 0))
                    price_data["price_change_1h_pct"] = float(pair["priceChange"].get("h1", 0))

                if chain_id not in result:
                    result[chain_id] = {}

                result[chain_id][dex_name] = price_data

            except Exception as e:
                print(f"[DEX] Error fetching {symbol} on {chain}: {e}")

        return result

    def get_best_price(self, symbol: str, chains: Optional[list[str]] = None) -> Optional[dict]:
        """
        Get the best (highest liquidity) DEX price across all chains.
        Returns best price opportunity with chain/dex details.
        """
        dex_data = self.get_dex_prices(symbol, chains)

        best = None
        best_liquidity = 0

        for chain, dexes in dex_data.items():
            for dex_name, price_info in dexes.items():
                if price_info.get("liquidity", 0) > best_liquidity:
                    best = {
                        "symbol": symbol,
                        "chain": chain,
                        "dex": dex_name,
                        **price_info,
                    }
                    best_liquidity = price_info.get("liquidity", 0)

        return best

    def compare_dex_cex_prices(self, symbol: str, cex_price: float) -> dict:
        """
        Compare CEX price against DEX prices.
        Returns arbitrage opportunities if price divergence > threshold.
        """
        dex_data = self.get_dex_prices(symbol)

        comparison = {
            "symbol": symbol,
            "cex_price": cex_price,
            "dex_best": None,
            "arbitrage_pct": 0,
            "all_dex_prices": dex_data,
            "fetched": datetime.now(timezone.utc).isoformat(),
        }

        if not dex_data:
            return comparison

        # Find best DEX price
        best_price = None
        best_liq = 0
        best_chain_dex = None

        for chain, dexes in dex_data.items():
            for dex_name, price_info in dexes.items():
                if price_info.get("price") and price_info.get("liquidity", 0) > best_liq:
                    best_price = price_info.get("price")
                    best_liq = price_info.get("liquidity", 0)
                    best_chain_dex = (chain, dex_name)

        if best_price and best_chain_dex:
            comparison["dex_best"] = {
                "chain": best_chain_dex[0],
                "dex": best_chain_dex[1],
                "price": best_price,
                "liquidity": best_liq,
            }
            # Positive = DEX is higher (opportunity to sell on DEX, buy on CEX)
            comparison["arbitrage_pct"] = ((best_price - cex_price) / cex_price) * 100

        return comparison
