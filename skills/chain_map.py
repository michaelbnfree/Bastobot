"""
Chain ecosystem taxonomy for the scanner.
Maps assets to parent chain, ecosystem, and layer.
Used for chain-context injection in alt snapshots and ecosystem-level alerts.
"""

CHAIN_MAP: dict[str, dict] = {
    # ── Bitcoin ───────────────────────────────────────────────────────────────
    "BTC":   {"chain": "BTC",  "ecosystem": "bitcoin",   "layer": "l1"},
    # ── Ethereum L1 ───────────────────────────────────────────────────────────
    "ETH":   {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l1"},
    "LINK":  {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l1"},
    "UNI":   {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l1"},
    "AAVE":  {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l1"},
    "MKR":   {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l1"},
    "LDO":   {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l1"},
    "PENDLE":{"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l1"},
    "ENS":   {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l1"},
    "PEPE":  {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l1", "type": "meme"},
    "SHIB":  {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l1", "type": "meme"},
    # ── Ethereum L2s ──────────────────────────────────────────────────────────
    "MATIC": {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l2", "chain_name": "Polygon"},
    "POL":   {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l2", "chain_name": "Polygon"},
    "ARB":   {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l2", "chain_name": "Arbitrum"},
    "OP":    {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l2", "chain_name": "Optimism"},
    "IMX":   {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l2", "chain_name": "Immutable X"},
    "STRK":  {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l2", "chain_name": "Starknet"},
    "BLAST": {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l2", "chain_name": "Blast"},
    "METIS": {"chain": "ETH",  "ecosystem": "ethereum",  "layer": "l2", "chain_name": "Metis"},
    # ── Solana ecosystem ──────────────────────────────────────────────────────
    "SOL":   {"chain": "SOL",  "ecosystem": "solana",    "layer": "l1"},
    "RAY":   {"chain": "SOL",  "ecosystem": "solana",    "layer": "l1"},
    "JUP":   {"chain": "SOL",  "ecosystem": "solana",    "layer": "l1"},
    "WIF":   {"chain": "SOL",  "ecosystem": "solana",    "layer": "l1", "type": "meme"},
    "BONK":  {"chain": "SOL",  "ecosystem": "solana",    "layer": "l1", "type": "meme"},
    "JTO":   {"chain": "SOL",  "ecosystem": "solana",    "layer": "l1"},
    "PYTH":  {"chain": "SOL",  "ecosystem": "solana",    "layer": "l1"},
    "DRIFT": {"chain": "SOL",  "ecosystem": "solana",    "layer": "l1"},
    "POPCAT":{"chain": "SOL",  "ecosystem": "solana",    "layer": "l1", "type": "meme"},
    # ── BNB Chain ─────────────────────────────────────────────────────────────
    "BNB":   {"chain": "BNB",  "ecosystem": "bnb",       "layer": "l1"},
    "CAKE":  {"chain": "BNB",  "ecosystem": "bnb",       "layer": "l1"},
    "BAKE":  {"chain": "BNB",  "ecosystem": "bnb",       "layer": "l1"},
    # ── Avalanche ecosystem ───────────────────────────────────────────────────
    "AVAX":  {"chain": "AVAX", "ecosystem": "avalanche", "layer": "l1"},
    "JOE":   {"chain": "AVAX", "ecosystem": "avalanche", "layer": "l1"},
    "GMX":   {"chain": "AVAX", "ecosystem": "avalanche", "layer": "l1"},
    # ── Monad (EVM L1) ────────────────────────────────────────────────────────
    "MON":   {"chain": "MON",  "ecosystem": "monad",     "layer": "l1"},
    # ── PoW independents ──────────────────────────────────────────────────────
    "LTC":   {"chain": "LTC",  "ecosystem": "pow",       "layer": "l1"},
    "BCH":   {"chain": "BCH",  "ecosystem": "pow",       "layer": "l1"},
    "DOGE":  {"chain": "DOGE", "ecosystem": "pow",       "layer": "l1", "type": "meme"},
    "KAS":   {"chain": "KAS",  "ecosystem": "pow",       "layer": "l1"},
    # ── Other L1s ─────────────────────────────────────────────────────────────
    "XRP":   {"chain": "XRP",  "ecosystem": "xrp",       "layer": "l1"},
    "ADA":   {"chain": "ADA",  "ecosystem": "cardano",   "layer": "l1"},
    "DOT":   {"chain": "DOT",  "ecosystem": "polkadot",  "layer": "l0"},
    "ATOM":  {"chain": "ATOM", "ecosystem": "cosmos",    "layer": "l1"},
    "NEAR":  {"chain": "NEAR", "ecosystem": "near",      "layer": "l1"},
    "APT":   {"chain": "APT",  "ecosystem": "aptos",     "layer": "l1"},
    "SUI":   {"chain": "SUI",  "ecosystem": "sui",       "layer": "l1"},
    "TIA":   {"chain": "TIA",  "ecosystem": "celestia",  "layer": "l0"},
    "INJ":   {"chain": "INJ",  "ecosystem": "injective", "layer": "l1"},
    "TON":   {"chain": "TON",  "ecosystem": "ton",       "layer": "l1"},
    "TRX":   {"chain": "TRX",  "ecosystem": "tron",      "layer": "l1"},
    "HBAR":  {"chain": "HBAR", "ecosystem": "hedera",    "layer": "l1"},
}

# L1 leaders — their price action dictates what happens to alts in their ecosystem
L1_LEADERS: dict[str, str] = {
    "ethereum": "ETH",
    "solana":   "SOL",
    "bnb":      "BNB",
    "avalanche":"AVAX",
    "bitcoin":  "BTC",
    "monad":    "MON",
}


def get_info(symbol: str) -> dict:
    return CHAIN_MAP.get(symbol.upper(), {})


def get_ecosystem(symbol: str) -> str | None:
    return CHAIN_MAP.get(symbol.upper(), {}).get("ecosystem")


def get_chain(symbol: str) -> str | None:
    return CHAIN_MAP.get(symbol.upper(), {}).get("chain")


def get_leader(symbol: str) -> str | None:
    """Return the L1 leader for this asset's ecosystem. None if it IS the leader or unknown."""
    info = CHAIN_MAP.get(symbol.upper(), {})
    eco  = info.get("ecosystem")
    if not eco:
        return None
    leader = L1_LEADERS.get(eco)
    return leader if leader and leader != symbol.upper() else None


def get_ecosystem_members(ecosystem: str) -> list[str]:
    return [k for k, v in CHAIN_MAP.items() if v.get("ecosystem") == ecosystem]


def is_l2(symbol: str) -> bool:
    return CHAIN_MAP.get(symbol.upper(), {}).get("layer") == "l2"


def ecosystem_label(symbol: str) -> str:
    """Human-readable label for Notion selects."""
    eco = get_ecosystem(symbol)
    labels = {
        "ethereum":  "Ethereum",
        "solana":    "Solana",
        "bnb":       "BNB Chain",
        "avalanche": "Avalanche",
        "bitcoin":   "Bitcoin",
        "pow":       "PoW",
        "monad":     "Monad",
        "xrp":       "XRP Ledger",
        "cardano":   "Cardano",
        "polkadot":  "Polkadot",
        "cosmos":    "Cosmos",
        "near":      "NEAR",
        "aptos":     "Aptos",
        "sui":       "Sui",
        "celestia":  "Celestia",
        "injective": "Injective",
        "ton":       "TON",
        "tron":      "Tron",
        "hedera":    "Hedera",
    }
    return labels.get(eco or "", eco.capitalize() if eco else "Unknown")
