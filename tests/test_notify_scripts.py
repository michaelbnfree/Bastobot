"""The notify_*.sh / health_check.sh scripts: real token, honest exit code, markers."""
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
GOOD = "123456789:" + "A" * 35
PLACEHOLDER = "***REDACTED_TELEGRAM_TOKEN***"

FAKE_CURL = """#!/bin/sh
echo "$@" >> "$FAKE_LOG_DIR/curl.log"
printf '%s' "${FAKE_CURL_CODE:-200}"
"""
FAKE_REDIS = """#!/bin/sh
echo "$@" >> "$FAKE_LOG_DIR/redis.log"
[ "$1" = get ] && [ "$2" = barry:last_kernel ] && printf '%s' "${FAKE_LAST_KERNEL:-}"
exit 0
"""


class ScriptCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        bindir = self.dir / "bin"
        bindir.mkdir()
        for name, body in (("curl", FAKE_CURL), ("redis-cli", FAKE_REDIS)):
            path = bindir / name
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        self.bindir = bindir

    def tearDown(self):
        self.tmp.cleanup()

    def env_file(self, token):
        path = self.dir / "env"
        path.write_text(f"OTHER=1\nTELEGRAM_BOT_TOKEN={token}\nNOTION_API_KEY=x\n")
        return path

    def run_script(self, name, token=GOOD, code="200", **extra):
        env = {
            "PATH": f"{self.bindir}:{os.environ['PATH']}",
            "BASTOBOT_ENV": str(self.env_file(token)),
            "FAKE_LOG_DIR": str(self.dir),
            "FAKE_CURL_CODE": code,
            **extra,
        }
        return subprocess.run(["bash", str(SCRIPTS / name)], env=env, capture_output=True, text=True, timeout=60)

    def log(self, name):
        path = self.dir / name
        return path.read_text() if path.exists() else ""


class TestSharedBehaviour(ScriptCase):
    SCRIPTS_WITH_SIMPLE_SEND = ("notify_reboot.sh",)

    def test_sends_with_the_token_from_env_file(self):
        result = self.run_script("notify_reboot.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"bot{GOOD}/sendMessage", self.log("curl.log"))

    def test_a_telegram_error_fails_the_script(self):
        """Production bug: a 404 still exited 0."""
        result = self.run_script("notify_reboot.sh", code="404")
        self.assertEqual(result.returncode, 1)
        self.assertIn("HTTP 404", result.stderr)

    def test_placeholder_or_missing_token_fails_before_calling_telegram(self):
        for token in (PLACEHOLDER, ""):
            self.setUp()
            result = self.run_script("notify_reboot.sh", token=token)
            self.assertEqual(result.returncode, 1)
            self.assertIn("TELEGRAM_BOT_TOKEN", result.stderr)
            self.assertEqual(self.log("curl.log"), "")

    def test_every_script_loads_the_token_through_the_helper(self):
        for name in ("health_check.sh", "notify_disk.sh", "notify_reboot.sh",
                     "notify_reboot_required.sh", "notify_restart.sh"):
            text = (SCRIPTS / name).read_text()
            self.assertIn("load_telegram_token || exit 1", text, name)
            self.assertNotIn("REDACTED", text, name)
            self.assertNotRegex(text, r'TOKEN="[^"]+"', name)


class TestDiskAlert(ScriptCase):
    def test_marker_is_only_written_after_a_delivered_alert(self):
        marker = self.dir / "disk-marker"
        failed = self.run_script("notify_disk.sh", code="404", THRESHOLD="0", NOTIFIED_MARKER=str(marker))
        self.assertEqual(failed.returncode, 1)
        self.assertFalse(marker.exists(), "a failed alert must not suppress the retry")
        ok = self.run_script("notify_disk.sh", THRESHOLD="0", NOTIFIED_MARKER=str(marker))
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertTrue(marker.exists())
        self.assertIn("Disk", self.log("curl.log"))


class TestRebootRequiredAlert(ScriptCase):
    def test_marker_is_only_written_after_a_delivered_alert(self):
        flag, marker = self.dir / "reboot-required", self.dir / "marker"
        flag.write_text("")
        failed = self.run_script("notify_reboot_required.sh", code="404",
                                 REBOOT_FLAG=str(flag), NOTIFIED_MARKER=str(marker))
        self.assertEqual(failed.returncode, 1)
        self.assertFalse(marker.exists())
        ok = self.run_script("notify_reboot_required.sh", REBOOT_FLAG=str(flag), NOTIFIED_MARKER=str(marker))
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertTrue(marker.exists())

    def test_nothing_is_sent_when_no_reboot_is_pending(self):
        result = self.run_script("notify_reboot_required.sh", REBOOT_FLAG=str(self.dir / "absent"),
                                 NOTIFIED_MARKER=str(self.dir / "m"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.log("curl.log"), "")


class TestRestartAlert(ScriptCase):
    def test_kernel_bookkeeping_is_only_cleared_after_a_delivered_message(self):
        failed = self.run_script("notify_restart.sh", code="404", FAKE_LAST_KERNEL="0.0.0-old")
        self.assertEqual(failed.returncode, 1)
        self.assertNotIn("del barry:last_kernel", self.log("redis.log"))
        ok = self.run_script("notify_restart.sh", FAKE_LAST_KERNEL="0.0.0-old")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("del barry:last_kernel", self.log("redis.log"))


class TestHealthCheck(ScriptCase):
    def test_placeholder_token_fails_immediately(self):
        result = self.run_script("health_check.sh", token=PLACEHOLDER)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.log("curl.log"), "")

    def test_summary_is_sent_through_the_helper(self):
        result = self.run_script("health_check.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"bot{GOOD}/sendMessage", self.log("curl.log"))


if __name__ == "__main__":
    unittest.main()
