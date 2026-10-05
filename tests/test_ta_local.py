"""Local TradingView-style rating: indicator math vs Pine, vote rules, summary thresholds.

The fixture (tests/fixtures/ta_pine_parity.json) holds 500 closed Binance candles for three
symbols/timeframes plus the last values of every indicator as computed by PineTS, a Pine
Script runtime (https://github.com/michaelbnfree/pinets), so these tests compare against
Pine's own ta.* functions, not against another copy of this code."""
import json
import unittest
from pathlib import Path

from skills import ta_local

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "ta_pine_parity.json").read_text())


class TestSeriesHelpers(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(ta_local.sma([1, 2, 3, 4, 5], 3), [None, None, 2, 3, 4])

    def test_ema_is_seeded_with_the_sma_of_the_first_n_values(self):
        self.assertEqual(ta_local.ema([1, 2, 3, 4, 5], 3), [None, None, 2, 3, 4])

    def test_rma_is_wilder_smoothing_seeded_with_the_sma(self):
        out = ta_local.rma([1, 2, 3, 4, 5], 3)
        self.assertEqual(out[:2], [None, None])
        self.assertAlmostEqual(out[2], 2.0)
        self.assertAlmostEqual(out[3], (4 + 2 * 2.0) / 3)

    def test_series_with_a_leading_none_prefix(self):
        self.assertEqual(ta_local.sma([None, None, 1, 2, 3], 2), [None, None, None, 1.5, 2.5])

    def test_wma(self):
        self.assertAlmostEqual(ta_local.wma([1, 2, 3], 3)[2], (1 * 1 + 2 * 2 + 3 * 3) / 6)

    def test_rsi_of_a_steadily_rising_series_is_100(self):
        self.assertEqual(ta_local.rsi(list(range(1, 40)))[-1], 100.0)

    def test_rsi_of_a_flat_then_falling_series_is_low(self):
        self.assertLess(ta_local.rsi([100.0 - i for i in range(40)])[-1], 1)

    def test_momentum(self):
        self.assertEqual(ta_local.momentum(list(range(20)), 10)[-1], 10)


class TestParityWithPine(unittest.TestCase):
    def test_every_indicator_matches_pine_on_all_three_datasets(self):
        checked = 0
        for name, data in FIXTURE.items():
            mine = ta_local.compute_values(data["candles"])
            for indicator, last3 in data["pine_last3"].items():
                expected = last3[-1]
                self.assertIsNotNone(mine.get(indicator), f"{name}:{indicator} missing")
                tolerance = 1e-8 * max(1.0, abs(expected))
                self.assertAlmostEqual(mine[indicator], expected, delta=tolerance, msg=f"{name}:{indicator}")
                checked += 1
        self.assertGreaterEqual(checked, 3 * 30)

    def test_previous_bar_values_match_pine_too(self):
        """The vote rules look at the previous bar; check [1] against Pine's second-to-last value."""
        data = FIXTURE["btc_4h"]
        values = ta_local.compute_values(data["candles"])
        for indicator in ("rsi", "stoch_k", "stoch_d", "cci", "plus_di", "minus_di", "ao", "mom", "wr", "bbp"):
            expected = data["pine_last3"][indicator][-2]
            self.assertAlmostEqual(values[indicator + "1"], expected, delta=1e-8 * max(1.0, abs(expected)), msg=indicator)


def values(**overrides):
    base = {
        "close": 100.0, "rsi": 50, "rsi1": 50, "stoch_k": 50, "stoch_d": 50, "stoch_k1": 50, "stoch_d1": 50,
        "bear": 0.0, "bear1": 0.0, "cci": 0, "cci1": 0,
        "adx": 10, "plus_di": 20, "minus_di": 20, "plus_di1": 20, "minus_di1": 20,
        "ao": 0.0, "ao1": 0.0, "ao2": 0.0, "mom": 0, "mom1": 0, "macd": 0, "macd_signal": 0,
        "stoch_rsi_k": 50, "stoch_rsi_d": 50, "wr": -50, "wr1": -50, "bbp": 0, "bbp1": 0, "uo": 50,
        "vwma": 100.0, "hma": 100.0, "ichi_conv": 100.0, "ichi_base": 100.0, "ichi_lead_a": 100.0, "ichi_lead_b": 100.0,
    }
    for n in (10, 20, 30, 50, 100, 200):
        base[f"ema{n}"] = base[f"sma{n}"] = 100.0
    base.update(overrides)
    return base


class TestOscillatorVotes(unittest.TestCase):
    def vote(self, name, **overrides):
        return ta_local.oscillator_votes(values(**overrides))[name]

    def test_everything_neutral_by_default(self):
        self.assertEqual(set(ta_local.oscillator_votes(values()).values()), {"NEUTRAL"})

    def test_rsi_oversold_and_rising_buys_overbought_and_falling_sells(self):
        self.assertEqual(self.vote("RSI", rsi=25, rsi1=22), "BUY")
        self.assertEqual(self.vote("RSI", rsi=25, rsi1=28), "NEUTRAL")
        self.assertEqual(self.vote("RSI", rsi=75, rsi1=78), "SELL")

    def test_stochastic_needs_the_crossover_on_the_previous_bar(self):
        self.assertEqual(self.vote("STOCH.K", stoch_k=15, stoch_d=10, stoch_k1=8, stoch_d1=12), "BUY")
        self.assertEqual(self.vote("STOCH.K", stoch_k=85, stoch_d=90, stoch_k1=92, stoch_d1=88), "SELL")
        # K already above D on the previous bar: TradingView voted NEUTRAL (ZEC 1d)
        self.assertEqual(self.vote("STOCH.K", stoch_k=15, stoch_d=10, stoch_k1=12, stoch_d1=10), "NEUTRAL")

    def test_k_equal_to_d_on_the_rail_is_not_a_cross(self):
        """BTC/XRP 1h: K and D both at 100 with a 1e-14 difference; TradingView voted NEUTRAL."""
        self.assertEqual(self.vote("STOCH.K", stoch_k=100.0, stoch_d=100.0 + 1e-14, stoch_k1=100, stoch_d1=97), "NEUTRAL")
        self.assertEqual(self.vote("Stoch.RSI", stoch_rsi_k=100.0, stoch_rsi_d=100.0 + 1e-14), "NEUTRAL")

    def test_stoch_rsi_models_only_the_sell_side(self):
        self.assertEqual(self.vote("Stoch.RSI", stoch_rsi_k=85, stoch_rsi_d=90), "SELL")
        self.assertEqual(self.vote("Stoch.RSI", stoch_rsi_k=85, stoch_rsi_d=80), "NEUTRAL")
        # TradingView voted NEUTRAL for K<20, D<20, K>D in 11 of 127 samples, so BUY is not voted
        self.assertEqual(self.vote("Stoch.RSI", stoch_rsi_k=15, stoch_rsi_d=10), "NEUTRAL")

    def test_cci(self):
        self.assertEqual(self.vote("CCI", cci=-150, cci1=-170), "BUY")
        self.assertEqual(self.vote("CCI", cci=150, cci1=170), "SELL")

    def test_adx_needs_a_trend_and_a_di_crossover(self):
        self.assertEqual(self.vote("ADX", adx=30, plus_di=30, minus_di=20, plus_di1=15, minus_di1=25), "BUY")
        self.assertEqual(self.vote("ADX", adx=15, plus_di=30, minus_di=20, plus_di1=15, minus_di1=25), "NEUTRAL")
        self.assertEqual(self.vote("ADX", adx=30, plus_di=15, minus_di=25, plus_di1=30, minus_di1=20), "SELL")

    def test_awesome_oscillator_zero_cross_and_saucer(self):
        self.assertEqual(self.vote("AO", ao=5, ao1=-1), "BUY")
        self.assertEqual(self.vote("AO", ao=5, ao1=4, ao2=6), "BUY")
        self.assertEqual(self.vote("AO", ao=-5, ao1=1), "SELL")

    def test_momentum_macd_and_ultimate_oscillator(self):
        self.assertEqual(self.vote("Mom", mom=10, mom1=5), "BUY")
        self.assertEqual(self.vote("Mom", mom=5, mom1=10), "SELL")
        self.assertEqual(self.vote("MACD", macd=2, macd_signal=1), "BUY")
        self.assertEqual(self.vote("MACD", macd=1, macd_signal=2), "SELL")
        self.assertEqual(self.vote("UO", uo=75), "BUY")
        self.assertEqual(self.vote("UO", uo=25), "SELL")

    def test_williams_r_and_bull_bear_power(self):
        self.assertEqual(self.vote("W%R", wr=-90, wr1=-95), "BUY")
        self.assertEqual(self.vote("W%R", wr=-10, wr1=-5), "SELL")

    def test_bull_bear_power_buys_on_a_negative_rising_bear_power_and_never_sells(self):
        self.assertEqual(self.vote("BBP", bear=-5, bear1=-8), "BUY")
        self.assertEqual(self.vote("BBP", bear=-8, bear1=-5), "NEUTRAL")
        self.assertEqual(self.vote("BBP", bear=5, bear1=2), "NEUTRAL")
        self.assertEqual(self.vote("BBP", bear=5, bear1=8, bbp=5, bbp1=8), "NEUTRAL")   # SELL is not modelled


class TestMovingAverageVotes(unittest.TestCase):
    def test_price_above_every_average_buys_below_sells(self):
        up = ta_local.moving_average_votes(values(close=110.0))
        self.assertEqual(len(up), 15)
        self.assertEqual(up["EMA200"], "BUY")
        self.assertEqual(up["VWMA"], "BUY")
        down = ta_local.moving_average_votes(values(close=90.0))
        self.assertEqual(down["SMA10"], "SELL")
        self.assertEqual(down["HullMA"], "SELL")

    def test_ichimoku_is_neutral_until_a_tradingview_vote_can_be_fitted(self):
        bullish = values(close=120.0, ichi_conv=110.0, ichi_base=100.0, ichi_lead_a=90.0, ichi_lead_b=80.0)
        self.assertEqual(ta_local.moving_average_votes(bullish)["Ichimoku"], "NEUTRAL")

    def test_price_on_the_average_is_neutral(self):
        self.assertEqual(ta_local.moving_average_votes(values())["EMA50"], "NEUTRAL")


class TestSummary(unittest.TestCase):
    def tally(self, buys, sells, neutrals):
        votes = {f"b{i}": "BUY" for i in range(buys)}
        votes.update({f"s{i}": "SELL" for i in range(sells)})
        votes.update({f"n{i}": "NEUTRAL" for i in range(neutrals)})
        return ta_local._tally(votes)[0]

    def test_counts_and_thresholds_match_tradingviews_scale(self):
        self.assertEqual(self.tally(16, 1, 9)["RECOMMENDATION"], "STRONG_BUY")   # 15/26 = 0.58
        self.assertEqual(self.tally(15, 3, 8)["RECOMMENDATION"], "BUY")          # 12/26 = 0.46
        self.assertEqual(self.tally(9, 7, 10)["RECOMMENDATION"], "NEUTRAL")      # 2/26 = 0.08
        self.assertEqual(self.tally(6, 11, 9)["RECOMMENDATION"], "SELL")         # -5/26 = -0.19
        self.assertEqual(self.tally(2, 18, 6)["RECOMMENDATION"], "STRONG_SELL")  # -16/26 = -0.62

    def test_counts_are_reported(self):
        self.assertEqual(self.tally(15, 3, 8), {"RECOMMENDATION": "BUY", "BUY": 15, "SELL": 3, "NEUTRAL": 8})


class TestComputeTa(unittest.TestCase):
    def test_shape_and_legacy_keys(self):
        ta = ta_local.compute_ta(FIXTURE["btc_4h"]["candles"])
        self.assertEqual(set(ta["summary"]), {"RECOMMENDATION", "BUY", "SELL", "NEUTRAL"})
        self.assertEqual(sum(ta["summary"][k] for k in ("BUY", "SELL", "NEUTRAL")), 26)
        self.assertEqual(len(ta["oscillators"]["COMPUTE"]), 11)
        self.assertEqual(len(ta["moving_averages"]["COMPUTE"]), 15)
        for key in ("rsi", "macd", "macd_signal", "adx", "ema_20", "ema_50", "ema_200", "bb_upper", "bb_lower", "bb_basis"):
            self.assertIsInstance(ta[key], float, key)
        self.assertGreater(ta["adx"], 0)       # the stub returned 0 for these
        self.assertGreater(ta["ema_200"], 0)
        self.assertEqual(ta["source"], "local")

    def test_bollinger_bands_surround_the_basis(self):
        ta = ta_local.compute_ta(FIXTURE["eth_1h"]["candles"])
        self.assertLess(ta["bb_lower"], ta["bb_basis"])
        self.assertLess(ta["bb_basis"], ta["bb_upper"])

    def test_too_few_candles_gives_no_rating(self):
        self.assertIsNone(ta_local.compute_ta(FIXTURE["btc_4h"]["candles"][:100]))
        self.assertIsNone(ta_local.compute_ta([]))
        self.assertIsNone(ta_local.compute_ta(None))

    def test_every_dataset_produces_a_rating(self):
        for name, data in FIXTURE.items():
            ta = ta_local.compute_ta(data["candles"])
            self.assertIsNotNone(ta, name)
            self.assertIn(ta["summary"]["RECOMMENDATION"],
                          {"STRONG_SELL", "SELL", "NEUTRAL", "BUY", "STRONG_BUY"}, name)


TV_VOTES = json.loads((Path(__file__).parent / "fixtures" / "ta_tv_votes.json").read_text())
NOT_MODELLED = {("BBP", "SELL"), ("Stoch.RSI", "BUY"), ("Ichimoku", "BUY"), ("Ichimoku", "SELL")}


def tv_candles(sample):
    rows = [[0, 0, h, l, c, v] for h, l, c, v in sample["hlcv"]]
    bar = sample["tv_last_bar"]     # both sides see TradingView's own forming bar
    rows[-1][2:6] = [bar["high"], bar["low"], bar["close"], bar["volume"]]
    return rows


class TestAgainstTradingViewVotes(unittest.TestCase):
    """13 coin/timeframe samples captured from TradingView (per-indicator votes) chosen to cover
    every non-neutral vote the rules reproduce. Refresh with tools/check_ta_parity.py."""

    def test_modelled_votes_match_tradingview(self):
        checked = mismatched = 0
        for sample in TV_VOTES:
            ta = ta_local.compute_ta(tv_candles(sample))
            ours = {**ta["oscillators"]["COMPUTE"], **ta["moving_averages"]["COMPUTE"]}
            for indicator, vote in sample["tv_votes"].items():
                if (indicator, vote) in NOT_MODELLED:
                    continue
                checked += 1
                mismatched += ours[indicator] != vote
        self.assertGreater(checked, 13 * 25)
        # a one-tick data difference between Binance and TradingView can flip a borderline vote
        self.assertLessEqual(mismatched, 2, f"{mismatched}/{checked} votes differ from TradingView")

    def test_every_non_neutral_tradingview_vote_that_is_modelled_is_reproduced(self):
        wanted = reproduced = 0
        for sample in TV_VOTES:
            ta = ta_local.compute_ta(tv_candles(sample))
            ours = {**ta["oscillators"]["COMPUTE"], **ta["moving_averages"]["COMPUTE"]}
            for indicator, vote in sample["tv_votes"].items():
                if vote != "NEUTRAL" and (indicator, vote) not in NOT_MODELLED:
                    wanted += 1
                    reproduced += ours[indicator] == vote
        self.assertGreaterEqual(reproduced / wanted, 0.97)

    def test_the_regime_class_matches_tradingview(self):
        def regime(recommendation):
            return "BULL" if "BUY" in recommendation else "BEAR" if "SELL" in recommendation else "CRAB"

        same = sum(
            regime(ta_local.compute_ta(tv_candles(s))["summary"]["RECOMMENDATION"]) == regime(s["tv_summary"]["RECOMMENDATION"])
            for s in TV_VOTES
        )
        self.assertGreaterEqual(same, len(TV_VOTES) - 1)


try:  # skills.trading needs numpy, which the venv lacks but the services' python has
    from skills import trading
except ImportError:
    trading = None


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


@unittest.skipIf(trading is None, "skills.trading needs numpy")
class TestLocalIndicatorsPath(unittest.TestCase):
    """_get_local_indicators is the scanner's primary TA path; it used to return a stub."""

    def run_path(self, payload_for):
        from unittest.mock import patch

        calls = []

        def fake_get(url, params=None, timeout=None):
            calls.append(params)
            return FakeResponse(payload_for(params["interval"]))

        with patch.object(trading.requests, "get", fake_get):
            return trading._get_local_indicators("BTC"), calls

    def test_real_rating_replaces_the_neutral_stub(self):
        candles = FIXTURE["btc_4h"]["candles"]
        result, calls = self.run_path(lambda interval: candles)
        self.assertEqual(set(result), {"1h", "4h", "1d"})
        for tf, ta in result.items():
            self.assertEqual(sum(ta["summary"][k] for k in ("BUY", "SELL", "NEUTRAL")), 26, tf)
            self.assertGreater(ta["adx"], 0, tf)
            self.assertGreater(ta["ema_50"], 0, tf)
        self.assertEqual({c["limit"] for c in calls}, {1000})

    def test_binance_error_payload_or_short_history_gives_no_rating_for_that_timeframe(self):
        candles = FIXTURE["btc_4h"]["candles"]
        result, _ = self.run_path(lambda i: {"code": -1121, "msg": "Invalid symbol."} if i == "1h" else candles[:100] if i == "4h" else candles)
        self.assertEqual(set(result), {"1d"})

    def test_nothing_usable_returns_none(self):
        result, _ = self.run_path(lambda interval: [])
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
