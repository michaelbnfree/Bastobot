"""Shared Telegram helper and the modules that used to carry a placeholder token."""
import contextlib
import io
import os
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from skills import telegram_alert, trade_monitor

try:  # skills.trading needs numpy, which the venv lacks but the services' python has
    from skills import trading
except ImportError:
    trading = None

ROOT = Path(__file__).resolve().parents[1]
GOOD = "123456789:" + "A" * 35
PLACEHOLDER = "***REDACTED_TELEGRAM_TOKEN***"


def response(status):
    resp = MagicMock()
    resp.ok = 200 <= status < 300
    resp.status_code = status
    resp.text = "ok" if resp.ok else "Not Found"
    return resp


def run(sender, text="hi", status=200, env=None):
    base = {"TELEGRAM_BOT_TOKEN": GOOD}
    base.update(env or {})
    out = io.StringIO()
    with patch.dict(os.environ, base, clear=False), patch.object(
        telegram_alert.requests, "post", return_value=response(status)
    ) as post, contextlib.redirect_stdout(out):
        result = sender(text)
    return result, post, out.getvalue()


class TestHelper(unittest.TestCase):
    def test_sends_with_the_env_token_and_reports_success(self):
        result, post, out = run(telegram_alert.send_telegram)
        self.assertTrue(result)
        self.assertIn(f"/bot{GOOD}/sendMessage", post.call_args.args[0])
        self.assertIn("[ALERT] Sent", out)

    def test_http_error_is_a_failure_not_a_send(self):
        result, _post, out = run(telegram_alert.send_telegram, status=404)
        self.assertFalse(result)
        self.assertIn("FAILED", out)
        self.assertNotIn("Sent", out)

    def test_placeholder_token_never_reaches_telegram(self):
        result, post, _out = run(telegram_alert.send_telegram, env={"TELEGRAM_BOT_TOKEN": PLACEHOLDER})
        self.assertFalse(result)
        post.assert_not_called()

    def test_chat_id_resolution(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in ("TELEGRAM_CHAT_ID", "BARRY_TELEGRAM_CHAT_ID"):
                os.environ.pop(key, None)
            self.assertEqual(telegram_alert.telegram_chat_id(), 298886049)
            os.environ["BARRY_TELEGRAM_CHAT_ID"] = "111"
            self.assertEqual(telegram_alert.telegram_chat_id(), 111)
            os.environ["TELEGRAM_CHAT_ID"] = "222"
            self.assertEqual(telegram_alert.telegram_chat_id(), 222)

    def test_fail_fast_on_bad_tokens(self):
        for value in ("", PLACEHOLDER, "nope"):
            with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": value}):
                with self.assertRaisesRegex(ValueError, "TELEGRAM_BOT_TOKEN"):
                    telegram_alert.require_telegram_config()


class TestModulesUseTheHelper(unittest.TestCase):
    def test_trade_monitor_alert_is_delivered_with_the_real_token(self):
        """Production bug: trade_monitor carried the placeholder, so SL/TP alerts 404'd."""
        result, post, out = run(trade_monitor._send_tg)
        self.assertTrue(result)
        self.assertIn(f"/bot{GOOD}/sendMessage", post.call_args.args[0])
        self.assertIn("[TRADE MON] Sent", out)

    def test_trade_monitor_reports_a_failed_delivery(self):
        result, _post, out = run(trade_monitor._send_tg, status=404)
        self.assertFalse(result)
        self.assertIn("[TRADE MON] FAILED", out)

    @unittest.skipIf(trading is None, "skills.trading needs numpy")
    def test_trading_rate_limit_alert_works_without_telegram_chat_id(self):
        """Production bug: TELEGRAM_CHAT_ID is not in .env, so this returned silently."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            result, post, _out = run(trading._send_telegram_alert, env={"BARRY_TELEGRAM_CHAT_ID": "298886049"})
        self.assertTrue(result)
        self.assertEqual(post.call_args.kwargs["json"]["chat_id"], 298886049)

    @unittest.skipIf(trading is None, "skills.trading needs numpy")
    def test_trading_alert_failure_is_visible(self):
        result, _post, out = run(trading._send_telegram_alert, env={"TELEGRAM_BOT_TOKEN": ""})
        self.assertFalse(result)
        self.assertIn("TELEGRAM_BOT_TOKEN", out)


class TestNoPlaceholderLeft(unittest.TestCase):
    def test_no_source_file_assigns_the_placeholder_token(self):
        pattern = re.compile(r'(TOKEN|_TG_TOKEN)\s*=\s*["\']\*\*\*REDACTED')
        offenders = []
        for folder in ("skills", "scripts", "api", "workers"):
            for path in (ROOT / folder).rglob("*"):
                if path.suffix in (".py", ".sh") and path.is_file():
                    if pattern.search(path.read_text(errors="ignore")):
                        offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
