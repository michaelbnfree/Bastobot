import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.main import classify


class TestApiClassification(unittest.TestCase):
    def test_routes_explicit_financial_messages(self):
        cases = (
            "btc price",
            "ETH chart",
            "what's SOL doing",
            "scan",
            "watch BTC",
            "unwatch ETH",
            "hot trades",
            "open trades",
            "positions",
            "pnl",
            "trade ETH long 3200 sl 3100 tp1 3400",
            "market update",
            "crypto market",
            "BTC funding",
            "HYPE perp setup",
            "setup",
            "setups",
            "show me setups",
        )

        for message in cases:
            with self.subTest(message=message):
                self.assertEqual(classify(message), "financial")

    def test_routes_casual_messages_to_medium(self):
        cases = (
            "how are you",
            "write me a text",
            "summarize this",
            "remind me later",
            "what is the weather",
            "is the farmers market open today",
            "how do I market my business better",
            "balance this paragraph",
            "what is the job market like",
        )

        for message in cases:
            with self.subTest(message=message):
                self.assertEqual(classify(message), "medium")


if __name__ == "__main__":
    unittest.main()
