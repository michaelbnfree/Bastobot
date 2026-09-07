import importlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


class TestBrainMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"BASTOBOT_BRAIN_ROOT": self.tmp.name})
        self.env.start()

        import skills.brain
        import skills.query_memory

        self.brain = importlib.reload(skills.brain)
        self.query_memory = importlib.reload(skills.query_memory)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_brain_dirs_are_created_explicitly(self):
        self.brain.ensure_brain_dirs()

        for subdir in ("trades", "watchlist", "patterns", "market", "learnings"):
            self.assertTrue((Path(self.tmp.name) / subdir).is_dir())

    def test_watchlist_context_is_available_by_symbol(self):
        self.brain.write_watchlist_note("BTC", "Macro leader", catalysts="Funding extremes")

        context = self.brain.get_brain_context("BTC")

        self.assertIn("BTC Watchlist Context", context)
        self.assertIn("Macro leader", context)

    def test_short_trade_risk_reward_uses_downside_target(self):
        path = self.brain.write_trade_note(
            symbol="BTC",
            direction="short",
            entry=100.0,
            tp1=95.0,
            tp2=90.0,
            sl=105.0,
        )

        content = Path(path).read_text(encoding="utf-8")
        self.assertIn("Risk/Reward:** 1:2.00", content)

    def test_trade_note_handles_missing_tp2(self):
        path = self.brain.write_trade_note(
            symbol="ETH",
            direction="long",
            entry=100.0,
            tp1=110.0,
            tp2=None,
            sl=95.0,
        )

        content = Path(path).read_text(encoding="utf-8")
        self.assertIn("TP2:** N/A", content)
        self.assertIn("Risk/Reward:** 1:2.00 (TP1)", content)

    def test_query_memory_saves_and_loads_last_query(self):
        self.query_memory.save_query("btc update", "financial", "BTC")

        last = self.query_memory.get_last_query()

        self.assertEqual(last["prompt"], "btc update")
        self.assertEqual(last["category"], "financial")
        self.assertEqual(last["asset"], "BTC")

    def test_latest_prompt_uses_recent_financial_context(self):
        self.query_memory.save_query("btc setup", "financial", "BTC")

        prompt = self.query_memory.get_context_prompt("what's the latest")

        self.assertIn("Last question about BTC", prompt)
        self.assertIn("price/market update", prompt)

    def test_latest_prompt_asks_confirmation_for_stale_context(self):
        stale = {
            "timestamp": (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=13)).isoformat(),
            "prompt": "eth setup",
            "category": "financial",
            "asset": "ETH",
        }
        log_path = Path(self.tmp.name) / "last_query.json"
        log_path.write_text(json.dumps(stale), encoding="utf-8")

        prompt = self.query_memory.get_context_prompt("what's the latest")

        self.assertIn("Your last query was about ETH", prompt)
        self.assertIn("Continue with that", prompt)


if __name__ == "__main__":
    unittest.main()
