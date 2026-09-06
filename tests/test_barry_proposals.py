import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from skills.barry_proposals import build_shadow_payload, emit_phase5_proposal

NOW = datetime(2026, 9, 6, 23, 0, tzinfo=UTC)
SECRET_HEX = "33" * 32


def decision(**overrides):
    item = {
        "timestamp": NOW.isoformat(),
        "action": "LONG",
        "asset": "BTC",
        "entry_price": 100,
        "stop_loss": 99,
        "take_profit": 102,
        "reasoning": "unit test",
    }
    item.update(overrides)
    return item


def key_file(directory: str) -> Path:
    path = Path(directory) / "proposal.env"
    path.write_text(
        "\n".join(
            (
                "BARRY_PROPOSAL_SOURCE_ID=bastobot-local",
                f"BARRY_PROPOSAL_HMAC_KEY_HEX={SECRET_HEX}",
            )
        )
    )
    path.chmod(0o600)
    return path


class TestBarryProposalBridge(unittest.TestCase):
    def test_bridge_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(emit_phase5_proposal(decision()))

    def test_valid_decision_emits_signed_phase5_file(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = Path(directory) / "inbox"
            with patch.dict(
                os.environ,
                {
                    "BARRY_PHASE5_PROPOSALS_ENABLED": "true",
                    "BARRY_PROPOSAL_KEY_FILE": str(key_file(directory)),
                    "BARRY_PHASE5_INBOX": str(inbox),
                    "BARRY_PROPOSAL_REQUESTED_RISK_USD": "0.10",
                    "BARRY_PROPOSAL_EXPECTED_EQUITY_USD": "100",
                },
                clear=True,
            ):
                path = emit_phase5_proposal(decision())
            self.assertIsNotNone(path)
            written = json.loads(path.read_text())
            self.assertEqual(written["version"], "barry-proposal-v1")
            self.assertEqual(written["source_id"], "bastobot-local")
            self.assertEqual(written["payload"]["proposal"]["symbol"], "BTC")
            self.assertEqual(written["payload"]["proposal"]["side"], "LONG")
            self.assertEqual(written["payload"]["proposal"]["requested_risk_usd"], "0.10")

    def test_bad_geometry_fails_closed(self):
        with self.assertRaises(ValueError):
            build_shadow_payload(decision(stop_loss=101), NOW)
        with self.assertRaises(ValueError):
            build_shadow_payload(
                decision(action="SHORT", stop_loss=99, take_profit=102),
                NOW,
            )

    def test_missing_price_fails_closed(self):
        with self.assertRaises(ValueError):
            build_shadow_payload(decision(entry_price=None), NOW)


if __name__ == "__main__":
    unittest.main()
