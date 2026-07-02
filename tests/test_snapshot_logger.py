from skills import snapshot_logger as sl


# ── validate_snapshot ───────────────────────────────────────────────────────

def test_no_flags_on_clean_agreeing_data():
    d1 = {
        "binance": {"price": 100000},
        "derivatives": {"mark_price": 100050, "funding_rate_pct": 0.01, "oi_usd_bn": 10},
        "bybit": {"mark_price": 100080, "funding_rate_pct": 0.01},
        "okx": {"funding_rate_pct": 0.01},
        "liquidations": {"total_liq_usd": 5_000_000, "okx_liq_usd": 3_000_000, "gate_liq_usd": 2_000_000},
    }
    assert sl.validate_snapshot(d1) == []


def test_source_error_is_flagged():
    d1 = {"binance_error": "timeout"}
    flags = sl.validate_snapshot(d1)
    assert any("Source error (binance): timeout" in f for f in flags)


def test_cross_source_price_spread_flagged_above_threshold():
    d1 = {
        "binance": {"price": 100000},
        "derivatives": {"mark_price": 100600, "funding_rate_pct": 0.01},  # 0.6% spread > 0.5%
    }
    flags = sl.validate_snapshot(d1)
    assert any("Price spread" in f for f in flags)


def test_cross_source_price_spread_not_flagged_within_threshold():
    d1 = {
        "binance": {"price": 100000},
        "derivatives": {"mark_price": 100100, "funding_rate_pct": 0.01},  # 0.1% spread
    }
    flags = sl.validate_snapshot(d1)
    assert not any("Price spread" in f for f in flags)


def test_funding_sign_mismatch_flagged():
    d1 = {
        "derivatives": {"mark_price": 100000, "funding_rate_pct": 0.01},
        "bybit": {"mark_price": 100000, "funding_rate_pct": -0.01},
    }
    flags = sl.validate_snapshot(d1)
    assert any("Funding sign mismatch" in f for f in flags)


def test_funding_sign_agreement_not_flagged():
    d1 = {
        "derivatives": {"mark_price": 100000, "funding_rate_pct": 0.01},
        "bybit": {"mark_price": 100000, "funding_rate_pct": 0.02},
    }
    flags = sl.validate_snapshot(d1)
    assert not any("Funding sign mismatch" in f for f in flags)


def test_liquidation_total_too_high_flagged():
    d1 = {"liquidations": {"total_liq_usd": 3_000_000_000}}
    flags = sl.validate_snapshot(d1)
    assert any("exceeds $2B" in f for f in flags)


def test_liquidation_total_too_low_flagged():
    d1 = {"liquidations": {"total_liq_usd": 10_000}}
    flags = sl.validate_snapshot(d1)
    assert any("unusually low" in f for f in flags)


def test_liquidation_gate_excluded_flagged():
    d1 = {
        "liquidations": {
            "total_liq_usd": 5_000_000,
            "gate_excluded": True,
            "gate_liq_usd": 100,
            "okx_liq_usd": 5_000_000,
        }
    }
    flags = sl.validate_snapshot(d1)
    assert any("Gate.io liq excluded" in f for f in flags)


def test_liquidation_source_divergence_flagged():
    d1 = {
        "liquidations": {
            "total_liq_usd": 5_000_000,
            "okx_liq_usd": 4_500_000,
            "gate_liq_usd": 500_000,  # 9x ratio > 5, but < 10 so not gate_excluded upstream
        }
    }
    flags = sl.validate_snapshot(d1)
    assert any("Liq source divergence" in f for f in flags)


def test_btc_price_out_of_range_flagged():
    d1 = {"binance": {"price": 999_999_999}}
    flags = sl.validate_snapshot(d1)
    assert any("outside valid range" in f for f in flags)


def test_funding_rate_out_of_normal_range_flagged():
    d1 = {"derivatives": {"mark_price": 100000, "funding_rate_pct": 0.9}}
    flags = sl.validate_snapshot(d1)
    assert any("out of normal range" in f for f in flags)


def test_two_call_price_identical_flagged_as_stale():
    d1 = {"binance": {"price": 100000}}
    d2 = {"binance": {"price": 100000}}
    flags = sl.validate_snapshot(d1, d2)
    assert any("Price identical" in f for f in flags)


def test_two_call_price_drift_over_1pct_flagged():
    d1 = {"binance": {"price": 100000}}
    d2 = {"binance": {"price": 102000}}
    flags = sl.validate_snapshot(d1, d2)
    assert any("Price moved" in f for f in flags)


def test_two_call_small_price_drift_not_flagged():
    d1 = {"binance": {"price": 100000}}
    d2 = {"binance": {"price": 100300}}
    flags = sl.validate_snapshot(d1, d2)
    assert not any("Price moved" in f for f in flags)
    assert not any("Price identical" in f for f in flags)


def test_two_call_oi_divergence_flagged():
    d1 = {"derivatives": {"mark_price": 100000, "funding_rate_pct": 0.01, "oi_usd_bn": 10}}
    d2 = {"derivatives": {"oi_usd_bn": 11}}  # 10% change > 5%
    flags = sl.validate_snapshot(d1, d2)
    assert any("OI diverged" in f for f in flags)


def test_two_call_funding_sign_flip_flagged():
    d1 = {"derivatives": {"mark_price": 100000, "funding_rate_pct": 0.02}}
    d2 = {"derivatives": {"funding_rate_pct": -0.02}}
    flags = sl.validate_snapshot(d1, d2)
    assert any("Funding rate sign flipped" in f for f in flags)


def test_two_call_new_failure_flagged():
    d1 = {"binance": {"price": 100}}
    d2 = {"binance": {"price": 100}, "okx_error": "timeout"}
    flags = sl.validate_snapshot(d1, d2)
    assert any("Sources failed on 2nd call only" in f for f in flags)


def test_two_call_recovered_source_flagged_informational():
    d1 = {"binance": {"price": 100}, "okx_error": "timeout"}
    d2 = {"binance": {"price": 100}}
    flags = sl.validate_snapshot(d1, d2)
    assert any("Sources recovered by 2nd call" in f for f in flags)


# ── _extract_bias ────────────────────────────────────────────────────────────

def test_extract_bias_explicit_bullish_tag():
    assert sl._extract_bias("Bias: Bullish — strong uptrend") == "Bullish"


def test_extract_bias_explicit_bearish_tag():
    assert sl._extract_bias("Bias: Bearish — breakdown likely") == "Bearish"


def test_extract_bias_bullish_keyword_in_first_300_chars():
    assert sl._extract_bias("Overall this looks bullish given the setup.") == "Bullish"


def test_extract_bias_sideways_keyword():
    assert sl._extract_bias("Market looks sideways and choppy right now.") == "Sideways"


def test_extract_bias_defaults_to_neutral():
    assert sl._extract_bias("No clear directional read here.") == "Neutral"


def test_extract_bias_bullish_checked_before_bearish_when_both_present():
    assert sl._extract_bias("Mixed signals: bullish momentum but bearish funding.") == "Bullish"


def test_extract_bias_bias_tag_matches_even_beyond_first_300_chars():
    text = ("x" * 400) + " Bias: Bullish"
    assert sl._extract_bias(text) == "Bullish"


def test_extract_bias_plain_keyword_beyond_300_chars_is_neutral():
    text = ("x" * 400) + " bullish"
    assert sl._extract_bias(text) == "Neutral"


# ── _avg_funding ─────────────────────────────────────────────────────────────

def test_avg_funding_no_sources_returns_none():
    assert sl._avg_funding({}) is None


def test_avg_funding_single_source():
    assert sl._avg_funding({"derivatives": {"funding_rate_pct": 0.01}}) == 0.01


def test_avg_funding_averages_multiple_sources():
    data = {
        "derivatives": {"funding_rate_pct": 0.01},
        "bybit": {"funding_rate_pct": 0.02},
        "okx": {"funding_rate_pct": 0.03},
    }
    assert sl._avg_funding(data) == 0.02


def test_avg_funding_rounds_to_four_decimals():
    data = {
        "derivatives": {"funding_rate_pct": 0.011111},
        "bybit": {"funding_rate_pct": 0.022222},
    }
    assert sl._avg_funding(data) == round((0.011111 + 0.022222) / 2, 4)
