from workers import tasks


# ── _detect_asset ────────────────────────────────────────────────────────────

def test_detect_asset_defaults_to_btc_on_empty_prompt():
    assert tasks._detect_asset("") == "BTC"
    assert tasks._detect_asset(None) == "BTC"


def test_detect_asset_matches_known_ticker_word():
    assert tasks._detect_asset("give me an ETH update") == "ETH"
    assert tasks._detect_asset("what about SOL price") == "SOL"


def test_detect_asset_word_boundary_avoids_bnb_inside_bonk():
    assert tasks._detect_asset("BONK is pumping hard") == "BONK"


def test_detect_asset_falls_back_to_name_substring_match():
    assert tasks._detect_asset("how's ethereum doing today") == "ETH"
    assert tasks._detect_asset("thoughts on cardano") == "ADA"


def test_detect_asset_defaults_to_btc_when_nothing_matches():
    assert tasks._detect_asset("what's the weather like") == "BTC"


# ── _detect_trade_horizon ────────────────────────────────────────────────────

def test_detect_trade_horizon_defaults_to_swing():
    assert tasks._detect_trade_horizon("") == "swing"
    assert tasks._detect_trade_horizon(None) == "swing"
    assert tasks._detect_trade_horizon("just checking the price") == "swing"


def test_detect_trade_horizon_scalp():
    assert tasks._detect_trade_horizon("give me a scalp setup") == "scalp"
    assert tasks._detect_trade_horizon("looking for a quick trade") == "scalp"


def test_detect_trade_horizon_day():
    assert tasks._detect_trade_horizon("day trade this for me") == "day"
    assert tasks._detect_trade_horizon("intraday setup please") == "day"


def test_detect_trade_horizon_position():
    assert tasks._detect_trade_horizon("looking for a position trade") == "position"
    assert tasks._detect_trade_horizon("long term hold thoughts") == "position"


# ── _is_snapshot_request ─────────────────────────────────────────────────────

def test_is_snapshot_request_false_on_empty():
    assert tasks._is_snapshot_request("") is False
    assert tasks._is_snapshot_request(None) is False


def test_is_snapshot_request_true_for_snapshot_keywords():
    assert tasks._is_snapshot_request("give me a market update") is True
    assert tasks._is_snapshot_request("BTC snapshot please") is True
    assert tasks._is_snapshot_request("give me a trade idea") is True


def test_is_snapshot_request_false_for_unrelated_prompt():
    assert tasks._is_snapshot_request("hello, how are you?") is False


# ── build_snapshot_instruction ───────────────────────────────────────────────

def test_build_snapshot_instruction_embeds_horizon_label_and_asset():
    text = tasks.build_snapshot_instruction("scalp", asset="ETH")
    assert 'PRIMARY SETUP section label MUST be exactly "SCALP"' in text
    assert "ETH Snapshot" in text
    assert "5M/15M/1H" in text


def test_build_snapshot_instruction_falls_back_to_swing_for_unknown_horizon():
    text = tasks.build_snapshot_instruction("not-a-real-horizon", asset="BTC")
    assert 'MUST be exactly "SWING"' in text


def test_build_snapshot_instruction_no_open_trade_note():
    text = tasks.build_snapshot_instruction("swing", asset="BTC", open_trade=None)
    assert "No open trades for this asset" in text
    assert "OPEN TRADE" not in text


def test_build_snapshot_instruction_includes_open_trade_context():
    open_trade = {
        "symbol": "BTC", "direction": "Long", "horizon": "swing",
        "entry": 100000.0, "sl": 95000.0, "tp1": 110000.0, "tp2": 120000.0,
        "entered_at": "2026-07-01T12:00:00+00:00",
    }
    text = tasks.build_snapshot_instruction("swing", asset="BTC", open_trade=open_trade)
    assert "OPEN TRADE" in text
    assert "Entry:     $100,000.00" in text
    assert "TP2:       $120,000.00" in text
    assert "Prior Trade Update" in text


def test_build_snapshot_instruction_open_trade_without_tp2():
    open_trade = {
        "symbol": "ETH", "direction": "Short", "horizon": "day",
        "entry": 3200.0, "sl": 3300.0, "tp1": 3000.0, "tp2": None,
        "entered_at": "2026-07-01T12:00:00+00:00",
    }
    text = tasks.build_snapshot_instruction("day", asset="ETH", open_trade=open_trade)
    assert "TP1:       $3,000.00" in text
    assert "TP2:" not in text.split("TP1:")[1].split("\n")[0]


# ── record_timing / get_avg_timing ───────────────────────────────────────────

def test_get_avg_timing_returns_none_when_no_data(fake_tasks_redis):
    assert tasks.get_avg_timing("financial") is None


def test_record_timing_and_average(fake_tasks_redis):
    tasks.record_timing("financial", 10.0)
    tasks.record_timing("financial", 20.0)
    tasks.record_timing("financial", 30.0)
    assert tasks.get_avg_timing("financial") == 20.0


def test_record_timing_trims_to_window(fake_tasks_redis):
    for i in range(1, 15):  # window is 10
        tasks.record_timing("financial", float(i))
    raw = tasks._redis.lrange("timing:financial", 0, -1)
    assert len(raw) == 10
    # most recent values (5..14) should be retained, oldest trimmed off
    assert set(float(v) for v in raw) == set(float(i) for i in range(5, 15))
