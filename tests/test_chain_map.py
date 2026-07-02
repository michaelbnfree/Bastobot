from skills import chain_map


def test_get_info_known_symbol_is_case_insensitive():
    assert chain_map.get_info("eth") == chain_map.get_info("ETH")
    assert chain_map.get_info("ETH")["ecosystem"] == "ethereum"


def test_get_info_unknown_symbol_returns_empty_dict():
    assert chain_map.get_info("NOPE") == {}


def test_get_ecosystem():
    assert chain_map.get_ecosystem("sol") == "solana"
    assert chain_map.get_ecosystem("UNKNOWN") is None


def test_get_chain():
    assert chain_map.get_chain("arb") == "ETH"
    assert chain_map.get_chain("UNKNOWN") is None


def test_get_leader_returns_ecosystem_leader():
    assert chain_map.get_leader("ARB") == "ETH"
    assert chain_map.get_leader("cake") == "BNB"


def test_get_leader_returns_none_for_the_leader_itself():
    assert chain_map.get_leader("ETH") is None
    assert chain_map.get_leader("BTC") is None


def test_get_leader_returns_none_for_unknown_symbol():
    assert chain_map.get_leader("NOPE") is None


def test_get_ecosystem_members_includes_expected_symbols():
    members = chain_map.get_ecosystem_members("solana")
    assert "SOL" in members
    assert "BONK" in members
    assert "ETH" not in members


def test_get_ecosystem_members_unknown_ecosystem_is_empty():
    assert chain_map.get_ecosystem_members("nope") == []


def test_is_l2_true_for_l2_chains():
    assert chain_map.is_l2("ARB") is True
    assert chain_map.is_l2("OP") is True


def test_is_l2_false_for_l1_and_unknown():
    assert chain_map.is_l2("ETH") is False
    assert chain_map.is_l2("NOPE") is False


def test_ecosystem_label_known_ecosystem():
    assert chain_map.ecosystem_label("BNB") == "BNB Chain"
    assert chain_map.ecosystem_label("SOL") == "Solana"


def test_ecosystem_label_unknown_symbol_is_unknown():
    assert chain_map.ecosystem_label("NOPE") == "Unknown"


def test_every_chain_map_entry_has_a_resolvable_leader_or_is_the_leader():
    """L1_LEADERS values must themselves be valid CHAIN_MAP entries."""
    for ecosystem, leader in chain_map.L1_LEADERS.items():
        assert leader in chain_map.CHAIN_MAP
        assert chain_map.CHAIN_MAP[leader]["ecosystem"] == ecosystem
