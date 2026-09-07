import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestExecutionGate(unittest.TestCase):
    def test_gate_defaults_to_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            from skills.execution_gate import exchange_mutations_enabled

            self.assertFalse(exchange_mutations_enabled())

    def test_false_values_remain_disabled(self):
        from skills.execution_gate import exchange_mutations_enabled

        for value in ("false", "0", "no", "off", ""):
            with self.subTest(value=value), patch.dict(
                os.environ,
                {"BASTOBOT_EXCHANGE_MUTATIONS_ENABLED": value},
                clear=True,
            ):
                self.assertFalse(exchange_mutations_enabled())

    def test_hyperliquid_mutations_stop_before_exchange_initialization(self):
        module = importlib.import_module("skills.active.hyperliquid")

        with patch.dict(
            os.environ,
            {"BASTOBOT_EXCHANGE_MUTATIONS_ENABLED": "false"},
            clear=True,
        ), patch.object(module, "_exchange") as exchange:
            mutation_calls = (
                lambda: module.set_leverage("BTC", 1),
                lambda: module.place_market_order("BTC", True, 20),
                lambda: module.place_limit_order("BTC", True, 20, 50_000),
                lambda: module.close_position("BTC"),
                lambda: module.cancel_order("BTC", 1),
                lambda: module.cancel_all_orders("BTC"),
            )

            for call in mutation_calls:
                with self.subTest(call=call), self.assertRaises(PermissionError):
                    call()

            exchange.assert_not_called()

if __name__ == "__main__":
    unittest.main()
