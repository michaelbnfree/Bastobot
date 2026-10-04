"""1h/4h regimes are published every scan cycle with a 1h TTL; missing TA is not faked."""
import json
import unittest
from unittest.mock import patch

from skills import scanner, snapshot_logger


class FakeRedis:
    def __init__(self, fail=False):
        self.store, self.fail = {}, fail

    def get(self, key):
        return self.store.get(key, (None, None))[1]

    def setex(self, key, ttl, value):
        if self.fail:
            raise ConnectionError("redis down")
        self.store[key] = (ttl, value)


def ta(rec_1h="SELL", rec_4h="BUY"):
    out = {}
    if rec_1h:
        out["1h"] = {"summary": {"RECOMMENDATION": rec_1h}}
    if rec_4h:
        out["4h"] = {"summary": {"RECOMMENDATION": rec_4h}}
    return {"ta": out, "binance": {"price": 85000.0}}


def publish(asset, data, redis=None):
    fake = redis or FakeRedis()
    with patch.object(snapshot_logger, "_get_redis", return_value=fake):
        result = snapshot_logger.publish_ta_regime(asset, data)
    return result, fake.store


class TestScanPublish(unittest.TestCase):
    def test_btc_writes_per_asset_and_shared_timeframe_keys_with_a_1h_ttl(self):
        result, store = publish("BTC", ta())
        self.assertTrue(result)
        for key in ("market:regime:1h", "market:regime:4h", "market:regime:BTC:1h",
                    "market:regime:BTC:4h", "market:regime_ta_meta", "market:regime_ta_meta:BTC"):
            self.assertEqual(store[key][0], 3600, key)
        self.assertEqual(store["market:regime:1h"][1], "BEAR")
        self.assertEqual(store["market:regime:4h"][1], "BULL")

    def test_it_never_touches_the_overall_bias_keys(self):
        _, store = publish("BTC", ta())
        self.assertNotIn("market:regime", store)
        self.assertNotIn("market:regime_meta", store)

    def test_eth_does_not_overwrite_the_shared_keys(self):
        _, store = publish("ETH", ta("BUY", "BUY"))
        self.assertEqual(
            sorted(store),
            ["market:regime:ETH:1h", "market:regime:ETH:4h", "market:regime_ta_meta:ETH"],
        )

    def test_a_missing_timeframe_is_skipped_not_published_as_sideways(self):
        """Production issue: a failed 1h TradingView fetch became '1h=CRAB'."""
        result, store = publish("BTC", ta(rec_1h=None))
        self.assertTrue(result)
        self.assertNotIn("market:regime:1h", store)
        self.assertNotIn("market:regime:BTC:1h", store)
        self.assertEqual(store["market:regime:4h"][1], "BULL")
        self.assertIsNone(json.loads(store["market:regime_ta_meta:BTC"][1])["regime_1h"])

    def test_no_ta_at_all_publishes_nothing(self):
        result, store = publish("BTC", ta(None, None))
        self.assertFalse(result)
        self.assertEqual(store, {})

    def test_meta_carries_the_age_a_consumer_needs_for_decay(self):
        _, store = publish("BTC", ta())
        meta = json.loads(store["market:regime_ta_meta:BTC"][1])
        self.assertEqual(meta["source"], "scan")
        self.assertEqual(meta["asset"], "BTC")
        self.assertIn("updated_at", meta)

    def test_a_redis_failure_is_reported_not_raised(self):
        result, _ = publish("BTC", ta(), redis=FakeRedis(fail=True))
        self.assertFalse(result)

    def test_case_and_default_asset(self):
        self.assertIn("market:regime:1h", publish("btc", ta())[1])
        self.assertIn("market:regime:BTC:1h", publish(None, ta())[1])


class TestSessionPublisherNoLongerFakesCrab(unittest.TestCase):
    def test_session_publish_skips_a_missing_timeframe_and_keeps_the_4h_overall_ttl(self):
        fake = FakeRedis()
        with patch.object(snapshot_logger, "_get_redis", return_value=fake):
            snapshot_logger._publish_regime("Bullish", ta(rec_1h=None), "BTC")
        self.assertNotIn("market:regime:1h", fake.store)
        self.assertEqual(fake.store["market:regime:4h"][0], 3600)
        self.assertEqual(fake.store["market:regime"], (14400, "BULL"))
        self.assertEqual(fake.store["market:regime_meta"][0], 14400)


class TestScannerWiring(unittest.TestCase):
    def test_every_scan_publishes_from_the_cycles_results(self):
        data = ta()
        with patch("skills.watchlist.get_all_symbols", return_value=["BTC"]), patch.object(
            scanner, "cache_age_seconds", return_value=10
        ), patch.object(scanner, "get_cached", return_value=data), patch.object(
            scanner, "check_alerts", return_value=[]
        ), patch.object(scanner, "_publish_scan_regimes") as publish_all:
            results = scanner.scan_all()
        publish_all.assert_called_once_with({"BTC": data})
        self.assertEqual(results, {"BTC": data})

    def test_one_symbol_failing_does_not_stop_the_others(self):
        calls = []

        def fake_publish(symbol, data):
            calls.append(symbol)
            if symbol == "BTC":
                raise RuntimeError("boom")

        with patch("skills.snapshot_logger.publish_ta_regime", fake_publish):
            scanner._publish_scan_regimes({"BTC": ta(), "ETH": ta()})
        self.assertEqual(calls, ["BTC", "ETH"])


if __name__ == "__main__":
    unittest.main()
