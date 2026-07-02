from skills import watchlist


def test_add_user_success(fake_watchlist_redis):
    ok, msg = watchlist.add_user("sol", "L1 narrative")
    assert ok is True
    assert "SOL" in msg
    items = watchlist.get_user()
    assert items == [{"symbol": "SOL", "narrative": "L1 narrative", "added": items[0]["added"]}]


def test_add_user_rejects_duplicate(fake_watchlist_redis):
    watchlist.add_user("SOL")
    ok, msg = watchlist.add_user("sol")
    assert ok is False
    assert "already on your watchlist" in msg
    assert len(watchlist.get_user()) == 1


def test_add_user_rejects_when_full(fake_watchlist_redis):
    for sym in ("A", "B", "C", "D", "E"):
        ok, _ = watchlist.add_user(sym)
        assert ok is True
    ok, msg = watchlist.add_user("F")
    assert ok is False
    assert "Watchlist full" in msg
    assert len(watchlist.get_user()) == watchlist.MAX_USER


def test_remove_user_success(fake_watchlist_redis):
    watchlist.add_user("SOL")
    ok, msg = watchlist.remove_user("sol")
    assert ok is True
    assert "Removed SOL" in msg
    assert watchlist.get_user() == []


def test_remove_user_not_found(fake_watchlist_redis):
    ok, msg = watchlist.remove_user("SOL")
    assert ok is False
    assert "not found" in msg


def test_update_narrative_success(fake_watchlist_redis):
    watchlist.add_user("SOL", "old narrative")
    ok, msg = watchlist.update_narrative("sol", "new narrative")
    assert ok is True
    assert watchlist.get_user()[0]["narrative"] == "new narrative"


def test_update_narrative_not_found(fake_watchlist_redis):
    ok, msg = watchlist.update_narrative("SOL", "narrative")
    assert ok is False
    assert "not found" in msg


def test_set_auto_caps_at_max_auto(fake_watchlist_redis):
    entries = [{"symbol": s} for s in ("A", "B", "C", "D")]
    watchlist.set_auto(entries)
    assert len(watchlist.get_auto()) == watchlist.MAX_AUTO
    assert watchlist.get_auto() == entries[: watchlist.MAX_AUTO]


def test_get_all_symbols_always_includes_btc(fake_watchlist_redis):
    watchlist.add_user("SOL")
    watchlist.set_auto([{"symbol": "ETH"}])
    symbols = watchlist.get_all_symbols()
    assert "BTC" in symbols
    assert "SOL" in symbols
    assert "ETH" in symbols


def test_get_all_symbols_does_not_duplicate_btc(fake_watchlist_redis):
    watchlist.add_user("BTC")
    symbols = watchlist.get_all_symbols()
    assert symbols.count("BTC") == 1


def test_format_watchlist_empty_state(fake_watchlist_redis):
    text = watchlist.format_watchlist()
    assert "User slots (0/5)" in text
    assert "Auto-scanned (0/3)" in text
    assert "empty — add up to 5" in text


def test_format_watchlist_populated_state(fake_watchlist_redis):
    watchlist.add_user("SOL", "L1 narrative")
    watchlist.set_auto([{"symbol": "ETH", "score": 7.5, "direction": "bullish"}])
    text = watchlist.format_watchlist()
    assert "SOL" in text
    assert "L1 narrative" in text
    assert "ETH" in text
    assert "[7.5/10]" in text
    assert "Bullish" in text
