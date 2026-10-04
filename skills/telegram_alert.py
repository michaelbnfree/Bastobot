"""Telegram alert helper: real token from the environment, honest delivery result.

Several modules used to carry their own copy of the bot token. A scrubbed
placeholder ("***REDACTED_TELEGRAM_TOKEN***") was committed in its place, so
every alert got a Telegram 404 while the logs said it was sent. All Python
senders now go through here; the notify_*.sh scripts use scripts/telegram_env.sh.
"""

import os
import re

import requests

DEFAULT_CHAT_ID = 298886049  # Michael's chat, the same one the gateway talks to
_TOKEN_FORMAT = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")


def telegram_token() -> str:
    """TELEGRAM_BOT_TOKEN from the environment (the service loads .env), validated."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not _TOKEN_FORMAT.fullmatch(token):
        raise ValueError(
            "FATAL: TELEGRAM_BOT_TOKEN is missing or not a bot token.\n"
            "Set it in /root/bastobot/.env (the same token the Telegram gateway uses)."
        )
    return token


def telegram_chat_id() -> int:
    raw = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("BARRY_TELEGRAM_CHAT_ID")
    return int(raw) if raw else DEFAULT_CHAT_ID


def require_telegram_config() -> None:
    """Fail fast at service start instead of silently dropping every alert."""
    telegram_token()


def send_telegram(text: str, label: str = "ALERT", parse_mode: str = "Markdown") -> bool:
    """Send a message; True only if Telegram accepted it. Failures are logged loudly."""
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{telegram_token()}/sendMessage",
            json={"chat_id": telegram_chat_id(), "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        if not resp.ok:
            print(f"[{label}] FAILED: Telegram HTTP {resp.status_code}: {resp.text[:200]}")
            return False
        print(f"[{label}] Sent: {text[:60]}")
        return True
    except Exception as e:
        print(f"[{label}] TG failed: {e}")
        return False
