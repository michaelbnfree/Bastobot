from skills import conviction


def test_no_data_yields_zero_low_bullish_default():
    result = conviction.score({}, symbol="")
    assert result["score"] == 0.0
    assert result["label"] == "Low"
    assert result["direction"] == "bullish"
    assert result["horizon"] == "swing"
    assert result["signals"] == []


def test_multi_tf_rsi_oversold_confluence_is_bullish():
    data = {
        "binance": {"price": 50000},
        "ta": {
            "1h": {"rsi": 15},
            "4h": {"rsi": 18},
            "1d": {"rsi": 25},
        },
    }
    result = conviction.score(data, symbol="")
    assert result["direction"] == "bullish"
    assert result["bull_pts"] == 7.5  # 2.0 + 2.0 + 1.0 + 2.5 confluence bonus
    assert result["bear_pts"] == 0.0
    assert any("high confluence" in s for s in result["signals"])


def test_multi_tf_rsi_overbought_confluence_is_bearish():
    data = {
        "binance": {"price": 50000},
        "ta": {
            "1h": {"rsi": 85},
            "4h": {"rsi": 82},
        },
    }
    result = conviction.score(data, symbol="")
    assert result["direction"] == "bearish"
    assert result["bear_pts"] == 6.5  # 2.0 + 2.0 + 2.5 confluence bonus
    assert any("high confluence" in s for s in result["signals"])


def test_horizon_scalp_from_1h_only():
    data = {"binance": {"price": 100}, "ta": {"1h": {"rsi": 15}}}
    result = conviction.score(data, symbol="")
    assert result["horizon"] == "scalp"


def test_horizon_day_from_4h_only():
    data = {"binance": {"price": 100}, "ta": {"4h": {"rsi": 15}}}
    result = conviction.score(data, symbol="")
    assert result["horizon"] == "day"


def test_horizon_swing_from_1d_only():
    data = {"binance": {"price": 100}, "ta": {"1d": {"rsi": 15}}}
    result = conviction.score(data, symbol="")
    assert result["horizon"] == "swing"


def test_ema_full_bull_stack():
    data = {
        "binance": {"price": 110},
        "ta": {"1d": {"ema_20": 105, "ema_50": 100, "ema_200": 90}},
    }
    result = conviction.score(data, symbol="")
    assert result["bull_pts"] == 2.0
    assert any("bull stack" in s for s in result["signals"])


def test_ema_full_bear_stack():
    data = {
        "binance": {"price": 80},
        "ta": {"1d": {"ema_20": 90, "ema_50": 100, "ema_200": 110}},
    }
    result = conviction.score(data, symbol="")
    assert result["bear_pts"] == 2.0
    assert any("bear stack" in s for s in result["signals"])


def test_adx_amplifies_existing_bull_direction():
    data = {
        "binance": {"price": 110},
        "ta": {"1d": {"ema_20": 105, "ema_50": 100, "ema_200": 90, "adx": 45}},
    }
    result = conviction.score(data, symbol="")
    # 2.0 from EMA stack + 1.0 ADX amplifier (adx > 40)
    assert result["bull_pts"] == 3.0
    assert any("strong trend confirms bull" in s for s in result["signals"])


def test_bollinger_lower_band_is_bullish_and_squeeze_detected():
    data = {
        "binance": {"price": 100},
        "ta": {"4h": {"bb_upper": 101, "bb_lower": 100, "bb_basis": 100.5}},
    }
    result = conviction.score(data, symbol="")
    assert result["bull_pts"] == 1.0
    assert any("oversold" in s for s in result["signals"])
    assert any("squeeze" in s for s in result["signals"])


def test_bollinger_upper_band_is_bearish():
    data = {
        "binance": {"price": 110},
        "ta": {"4h": {"bb_upper": 110, "bb_lower": 90, "bb_basis": 100}},
    }
    result = conviction.score(data, symbol="")
    assert result["bear_pts"] == 1.0
    assert any("overbought" in s for s in result["signals"])


def test_extreme_negative_funding_is_contrarian_bullish():
    data = {"binance": {"price": 100}, "derivatives": {"funding_rate_pct": -0.15}}
    result = conviction.score(data, symbol="")
    assert result["bull_pts"] == 2.0
    assert any("contrarian bullish" in s for s in result["signals"])


def test_extreme_positive_funding_is_contrarian_bearish():
    data = {"binance": {"price": 100}, "derivatives": {"funding_rate_pct": 0.15}}
    result = conviction.score(data, symbol="")
    assert result["bear_pts"] == 2.0
    assert any("contrarian bearish" in s for s in result["signals"])


def test_oi_and_price_bullish_continuation():
    data = {
        "binance": {"price": 100, "change_24h_pct": 2},
        "derivatives": {"oi_change_24h_pct": 6},
    }
    result = conviction.score(data, symbol="")
    assert result["bull_pts"] == 1.0
    assert any("bullish continuation" in s for s in result["signals"])


def test_oi_deleveraging_signal_has_no_directional_points():
    data = {
        "binance": {"price": 100, "change_24h_pct": 2},
        "derivatives": {"oi_change_24h_pct": -6},
    }
    result = conviction.score(data, symbol="")
    assert result["bull_pts"] == 0.0
    assert result["bear_pts"] == 0.0
    assert any("deleveraging" in s for s in result["signals"])


def test_extreme_fear_is_contrarian_bullish():
    data = {"binance": {"price": 100}, "fear_greed": {"score": 5}}
    result = conviction.score(data, symbol="")
    assert result["bull_pts"] == 2.0
    assert any("extreme fear" in s for s in result["signals"])


def test_extreme_greed_is_contrarian_bearish():
    data = {"binance": {"price": 100}, "fear_greed": {"score": 95}}
    result = conviction.score(data, symbol="")
    assert result["bear_pts"] == 2.0
    assert any("extreme greed" in s for s in result["signals"])


def test_volume_spike_confirms_dominant_side():
    data = {
        "binance": {"price": 100, "volume_change_pct": 60},
        "fear_greed": {"score": 5},  # seeds a bullish lean so the spike confirms it
    }
    result = conviction.score(data, symbol="")
    assert result["bull_pts"] == 3.0  # 2.0 fear/greed + 1.0 volume confirmation
    assert any("Volume spike" in s for s in result["signals"])


def test_mixed_signals_are_penalized_and_dominance_below_60_pct():
    data = {
        "binance": {"price": 100},
        "ta": {
            "4h": {"macd": 1.0, "macd_signal": 0.5},
            "1d": {"macd": 0.2, "macd_signal": 0.3},
        },
    }
    result = conviction.score(data, symbol="")
    assert result["bull_pts"] == 0.5
    assert result["bear_pts"] == 0.5
    # dominance is exactly 50% (< 60%), so score gets the 0.65 mixed-signal penalty
    assert result["score"] == 0.2
    assert result["label"] == "Low"


def test_label_thresholds():
    assert conviction.score({}, symbol="")["label"] == "Low"

    high_conviction = {
        "binance": {"price": 50000},
        "ta": {
            "1h": {"rsi": 15},
            "4h": {"rsi": 15},
            "1d": {"rsi": 15, "ema_20": 100, "ema_50": 90, "ema_200": 80},
        },
    }
    result = conviction.score(high_conviction, symbol="")
    assert result["score"] >= 6.0
    assert result["label"] in ("High", "Very High")


def test_divergence_detected_against_cached_previous_snapshot(fake_redis):
    first = {
        "binance": {"price": 100},
        "ta": {"4h": {"rsi": 50}, "1d": {"rsi": 50}},
    }
    conviction.score(first, symbol="DIVTEST")

    # price falls >0.5%, RSI rises >1 point on 4h -> bullish divergence
    second = {
        "binance": {"price": 98},
        "ta": {"4h": {"rsi": 55}, "1d": {"rsi": 50}},
    }
    result = conviction.score(second, symbol="DIVTEST")
    assert result["bull_pts"] >= 2.0
    assert any("Bullish RSI divergence" in s for s in result["signals"])


def test_score_is_cached_and_retrievable(fake_redis):
    result = conviction.score({"binance": {"price": 100}}, symbol="CACHETEST")
    cached = conviction.get_cached("CACHETEST")
    assert cached == result


def test_get_cached_returns_none_when_absent(fake_redis):
    assert conviction.get_cached("NOPE") is None


def test_format_conviction_lists_signals():
    data = {"binance": {"price": 50000}, "ta": {"1h": {"rsi": 15}, "4h": {"rsi": 15}}}
    result = conviction.score(data, symbol="")
    text = conviction.format_conviction(result, symbol="BTC")
    assert "BTC" in text
    assert result["label"] in text
    for s in result["signals"]:
        assert s in text


def test_format_conviction_handles_no_signals():
    result = conviction.score({}, symbol="")
    text = conviction.format_conviction(result, symbol="BTC")
    assert "no strong signals detected" in text
