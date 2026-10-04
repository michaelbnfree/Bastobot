"""DEX look-alike rejection, Notion log cooldown, and per-asset regime keys."""
import json
import unittest
from unittest.mock import MagicMock, patch

from skills import dexscreener_client, scanner, snapshot_logger
from skills.dexscreener_client import DexScreenerClient

CEX = 85000.0


def pair(price, liquidity=5_000_000, dex="uniswap", chain="ethereum", symbol="BTC"):
    return {
        "chainId": chain,
        "dexId": dex,
        "priceUsd": str(price),
        "liquidity": {"usd": liquidity},
        "volume": {"h24": 1000},
        "baseToken": {"symbol": symbol},
        "quoteToken": {"symbol": "USDC"},
        "pairAddress": "0xabc",
    }


def client_with(pairs):
    client = DexScreenerClient()
    response = MagicMock()
    response.json.return_value = {"pairs": pairs}
    response.raise_for_status.return_value = None
    client.session = MagicMock()
    client.session.get.return_value = response
    return client


class TestLookAlikeRejection(unittest.TestCase):
    def test_scam_token_priced_far_from_cex_is_rejected(self):
        """Production bug: a $0.0012 'BTC' with fake liquidity became an arb row."""
        client = client_with([pair(0.0012, liquidity=6_000_000_000)])
        comparison = client.compare_dex_cex_prices("BTC", CEX)
        self.assertIsNone(comparison["dex_best"])
        self.assertEqual(comparison["arbitrage_pct"], 0)

    def test_depegged_pair_26_percent_off_is_rejected(self):
        client = client_with([pair(62362.73, liquidity=22_000_000)])
        self.assertIsNone(client.compare_dex_cex_prices("BTC", CEX)["dex_best"])

    def test_real_pair_is_found_behind_a_fake_first_result(self):
        client = client_with([pair(0.0012, liquidity=6_000_000_000), pair(85400.0)])
        best = client.compare_dex_cex_prices("BTC", CEX)["dex_best"]
        self.assertEqual(best["price"], 85400.0)

    def test_small_real_spread_is_kept(self):
        client = client_with([pair(86000.0)])
        comparison = client.compare_dex_cex_prices("BTC", CEX)
        self.assertAlmostEqual(comparison["arbitrage_pct"], (86000 - CEX) / CEX * 100)

    def test_without_a_reference_price_behaviour_is_unchanged(self):
        client = client_with([pair(0.0012), pair(85400.0)])
        self.assertEqual(client._search_token("BTC", "ethereum")["priceUsd"], "0.0012")

    def test_deviation_helper_edges(self):
        self.assertTrue(dexscreener_client._within_deviation("106250", CEX))   # +25.0%
        self.assertFalse(dexscreener_client._within_deviation("106260", CEX))
        self.assertFalse(dexscreener_client._within_deviation(None, CEX))
        self.assertFalse(dexscreener_client._within_deviation("0", CEX))


class TestNotionCooldown(unittest.TestCase):
    DATA = {
        "dex_comparison": {
            "arbitrage_pct": 3.0,
            "dex_best": {"chain": "ethereum", "dex": "uniswap", "price": 87550.0, "liquidity": 5_000_000},
            "all_dex_prices": {},
        }
    }

    def run_cycles(self, cycles):
        in_cooldown = set()

        def fake_cooldown(symbol, condition, ttl):
            key = (symbol, condition)
            if key in in_cooldown:
                return True
            in_cooldown.add(key)
            return False

        with patch.object(scanner, "_cooldown", fake_cooldown), patch.object(
            scanner, "send_alert"
        ) as alert, patch("skills.dex_monitor.log_opportunity") as monitor, patch(
            "skills.dex_notion_logger.log_arbitrage_opportunity"
        ) as notion:
            for _ in range(cycles):
                scanner._check_dex_arbitrage("BTC", CEX, self.DATA)
        return monitor.call_count, notion.call_count, alert.call_count

    def test_notion_and_telegram_log_once_per_cooldown_but_redis_every_cycle(self):
        monitor, notion, alert = self.run_cycles(5)
        self.assertEqual(monitor, 5)
        self.assertEqual(notion, 1)
        self.assertEqual(alert, 1)

    def test_below_threshold_spread_is_not_sent_to_notion(self):
        data = json.loads(json.dumps(self.DATA))
        data["dex_comparison"]["arbitrage_pct"] = 0.4
        with patch.object(scanner, "_cooldown", return_value=False), patch.object(
            scanner, "send_alert"
        ) as alert, patch("skills.dex_monitor.log_opportunity"), patch(
            "skills.dex_notion_logger.log_arbitrage_opportunity"
        ) as notion:
            self.assertEqual(scanner._check_dex_arbitrage("BTC", CEX, data), [])
        notion.assert_not_called()
        alert.assert_not_called()


class FakeRedis:
    def __init__(self):
        self.store = {}

    def setex(self, key, ttl, value):
        self.store[key] = (ttl, value)


class TestRegimeKeys(unittest.TestCase):
    DATA = {"ta": {"1h": {"summary": {"RECOMMENDATION": "SELL"}}, "4h": {"summary": {"RECOMMENDATION": "BUY"}}}}

    def publish(self, asset, bias="Bullish"):
        fake = FakeRedis()
        with patch.object(snapshot_logger, "_get_redis", return_value=fake):
            snapshot_logger._publish_regime(bias, self.DATA, asset)
        return fake.store

    def test_btc_writes_the_shared_keys_and_its_own(self):
        store = self.publish("BTC")
        for key in ("market:regime", "market:regime:1h", "market:regime:4h", "market:regime_meta",
                    "market:regime:BTC", "market:regime:BTC:1h", "market:regime:BTC:4h",
                    "market:regime_meta:BTC"):
            self.assertIn(key, store)
        self.assertEqual(store["market:regime:1h"][1], "BEAR")
        self.assertEqual(store["market:regime:4h"][1], "BULL")

    def test_eth_does_not_overwrite_the_shared_keys(self):
        store = self.publish("ETH", bias="Neutral")
        self.assertEqual(
            sorted(store),
            ["market:regime:ETH", "market:regime:ETH:1h", "market:regime:ETH:4h", "market:regime_meta:ETH"],
        )

    def test_every_key_has_a_four_hour_ttl(self):
        for asset in ("BTC", "ETH"):
            for key, (ttl, _value) in self.publish(asset).items():
                self.assertEqual(ttl, 4 * 3600, key)

    def test_asset_defaults_to_btc_and_is_case_insensitive(self):
        self.assertIn("market:regime:1h", self.publish("btc"))
        self.assertIn("market:regime:BTC:1h", self.publish(None))


if __name__ == "__main__":
    unittest.main()
