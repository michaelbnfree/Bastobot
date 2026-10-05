"""bybit_forward_signal must not trade on a stale option chain and must survive a freshly rotated log."""
import gzip
import importlib.util
import io
import json
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "bybit_forward_signal.py"
spec = importlib.util.spec_from_file_location("bybit_forward_signal", SCRIPT)
sig = importlib.util.module_from_spec(spec)
sys.modules["bybit_forward_signal"] = sig
spec.loader.exec_module(sig)

NOW = 1_800_000_000_000          # fixed "current time" in ms


def snapshot(age_ms=300_000, marker=0):
    captured = NOW - age_ms
    ticker = lambda side: {"symbol": f"BTC-14FEB27-90000-{side}-USDT", "underlyingPrice": "90000", "markIv": "0.60",
                           "openInterest": "10"}
    return {"captured_at": f"t{marker}", "captured_epoch_ms": captured, "tickers": [ticker("C"), ticker("P")]}


def line(snap):
    return json.dumps(snap, separators=(",", ":")) + "\n"


class TestLoadLatestSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.live = self.dir / "btc_option_chain.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_the_last_record_of_a_multi_megabyte_file(self):
        filler = {"captured_at": "old", "captured_epoch_ms": NOW - 10 * 3600_000, "pad": "x" * 700_000}
        self.live.write_text(line(filler) * 5 + line(snapshot(marker=7)))
        self.assertEqual(sig.load_latest_snapshot(self.live, NOW)["captured_at"], "t7")

    def test_single_record_file_without_trailing_newline(self):
        self.live.write_text(line(snapshot(marker=3)).rstrip("\n"))
        self.assertEqual(sig.load_latest_snapshot(self.live, NOW)["captured_at"], "t3")

    def test_empty_live_file_falls_back_to_newest_rotated_raw_file(self):
        self.live.write_text("")
        (self.dir / "btc_option_chain.jsonl-20261004").write_text(line(snapshot(age_ms=86_400_000)))
        (self.dir / "btc_option_chain.jsonl-20261005").write_text(line(snapshot(marker=5)))
        self.assertEqual(sig.load_latest_snapshot(self.live, NOW)["captured_at"], "t5")

    def test_missing_live_file_falls_back_to_a_gzipped_rotated_file(self):
        with gzip.open(self.dir / "btc_option_chain.jsonl-20261005.gz", "wt") as handle:
            handle.write(line(snapshot(age_ms=400_000, marker=1)) + line(snapshot(marker=9)))
        self.assertEqual(sig.load_latest_snapshot(self.live, NOW)["captured_at"], "t9")

    def test_nothing_anywhere_is_an_error_not_an_index_error(self):
        with self.assertRaises(sig.StaleSnapshotError):
            sig.load_latest_snapshot(self.live, NOW)
        self.live.write_text("")
        with self.assertRaises(sig.StaleSnapshotError):
            sig.load_latest_snapshot(self.live, NOW)

    def test_normal_age_and_one_missed_tick_are_accepted(self):
        for age in (1_000, 300_000, 600_000, sig.MAX_SNAPSHOT_AGE_MS):
            self.live.write_text(line(snapshot(age_ms=age)))
            sig.load_latest_snapshot(self.live, NOW)

    def test_stale_snapshot_is_rejected_with_a_clear_message(self):
        self.live.write_text(line(snapshot(age_ms=sig.MAX_SNAPSHOT_AGE_MS + 1)))
        with self.assertRaises(sig.StaleSnapshotError) as ctx:
            sig.load_latest_snapshot(self.live, NOW)
        self.assertIn("collector", str(ctx.exception))

    def test_a_stale_seeded_or_rotated_record_is_rejected_too(self):
        self.live.write_text("")
        (self.dir / "btc_option_chain.jsonl-20261005").write_text(line(snapshot(age_ms=3 * 3600_000)))
        with self.assertRaises(sig.StaleSnapshotError):
            sig.load_latest_snapshot(self.live, NOW)

    def test_a_snapshot_from_the_future_is_rejected(self):
        self.live.write_text(line(snapshot(age_ms=-10 * 60_000)))
        with self.assertRaises(sig.StaleSnapshotError):
            sig.load_latest_snapshot(self.live, NOW)
        self.live.write_text(line(snapshot(age_ms=-30_000)))      # small clock skew is fine
        sig.load_latest_snapshot(self.live, NOW)


class TestMainWritesOnlyFreshSignals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.saved = (sig.OPTION_FILE, sig.OUTPUT, sig.rv_30d)
        sig.OPTION_FILE, sig.OUTPUT = d / "btc_option_chain.jsonl", d / "signals.jsonl"
        sig.rv_30d = lambda captured_ms: (0.40, "test", True)

    def tearDown(self):
        sig.OPTION_FILE, sig.OUTPUT, sig.rv_30d = self.saved
        self.tmp.cleanup()

    def test_fresh_snapshot_writes_a_signal(self):
        sig.OPTION_FILE.write_text(line(snapshot(marker=1)))
        with redirect_stdout(io.StringIO()):
            sig.main(NOW)
        record = json.loads(sig.OUTPUT.read_text().splitlines()[-1])
        self.assertEqual(record["captured_at"], "t1")
        self.assertEqual(record["signal"], "SELL_VOL")          # IV 0.60 vs RV 0.40

    def test_stale_snapshot_writes_nothing(self):
        sig.OPTION_FILE.write_text(line(snapshot(age_ms=2 * 3600_000)))
        with self.assertRaises(sig.StaleSnapshotError):
            sig.main(NOW)
        self.assertFalse(sig.OUTPUT.exists())

    def test_empty_live_file_after_rotation_still_signals_from_the_rotated_file(self):
        sig.OPTION_FILE.write_text("")
        (sig.OPTION_FILE.parent / "btc_option_chain.jsonl-20261005").write_text(line(snapshot(marker=4)))
        with redirect_stdout(io.StringIO()):
            sig.main(NOW)
        self.assertEqual(json.loads(sig.OUTPUT.read_text())["captured_at"], "t4")


class TestScriptExit(unittest.TestCase):
    def test_importing_the_module_has_no_side_effects(self):
        self.assertTrue(callable(sig.main))                     # exec_module above ran nothing


if __name__ == "__main__":
    unittest.main()
