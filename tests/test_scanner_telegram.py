"""Scanner Telegram alerts: real token from env, honest result, fail fast."""
import contextlib
import io
import os
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from skills import scanner

GOOD_TOKEN = "123456789:" + "A" * 35
PLACEHOLDER = "***REDACTED_TELEGRAM_TOKEN***"


def response(status):
    resp = MagicMock()
    resp.ok = 200 <= status < 300
    resp.status_code = status
    resp.text = "ok" if resp.ok else '{"ok":false,"error_code":404,"description":"Not Found"}'
    return resp


def send(env_token, status=200):
    env = {} if env_token is None else {"TELEGRAM_BOT_TOKEN": env_token}
    out = io.StringIO()
    with patch.dict(os.environ, env, clear=False), patch.object(
        scanner.requests, "post", return_value=response(status)
    ) as post, contextlib.redirect_stdout(out):
        if env_token is None:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        result = scanner.send_alert("hello")
    return result, post, out.getvalue()


class TestSendAlert(unittest.TestCase):
    def test_uses_the_token_from_the_environment(self):
        result, post, out = send(GOOD_TOKEN)
        self.assertTrue(result)
        self.assertIn(f"/bot{GOOD_TOKEN}/sendMessage", post.call_args.args[0])
        self.assertIn("[ALERT] Sent", out)

    def test_http_error_is_reported_not_called_sent(self):
        """Production bug: a 404 was logged as '[ALERT] Sent'."""
        result, _post, out = send(GOOD_TOKEN, status=404)
        self.assertFalse(result)
        self.assertIn("[ALERT] FAILED", out)
        self.assertIn("404", out)
        self.assertNotIn("[ALERT] Sent", out)

    def test_placeholder_token_is_refused_without_calling_telegram(self):
        result, post, out = send(PLACEHOLDER)
        self.assertFalse(result)
        post.assert_not_called()
        self.assertIn("TELEGRAM_BOT_TOKEN", out)
        self.assertNotIn("[ALERT] Sent", out)

    def test_missing_token_is_refused_without_calling_telegram(self):
        result, post, _out = send(None)
        self.assertFalse(result)
        post.assert_not_called()


class TestFailFast(unittest.TestCase):
    def test_missing_or_placeholder_token_raises_a_clear_error(self):
        for value in ("", PLACEHOLDER, "not-a-token"):
            with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": value}):
                with self.assertRaisesRegex(ValueError, "TELEGRAM_BOT_TOKEN"):
                    scanner.require_telegram_config()

    def test_valid_token_passes(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": GOOD_TOKEN}):
            scanner.require_telegram_config()

    def test_the_service_checks_before_it_starts_scanning(self):
        source = Path(__file__).resolve().parents[1].joinpath("scripts/scanner_service.py").read_text()
        main = source[source.index("def main()"):]
        self.assertLess(main.index("require_telegram_config()"), main.index("while True"))

    def test_no_token_literal_is_left_in_the_scanner_source(self):
        source = Path(scanner.__file__).read_text()
        self.assertIsNone(re.search(r'_TG_TOKEN\s*=\s*"', source))


if __name__ == "__main__":
    unittest.main()
