"""BastoBot-to-Barry signed proposal bridge.

This module is intentionally file-based and mutation-free. BastoBot may emit
authenticated trade proposals for Barry to evaluate, but it must not submit
exchange orders.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4

_TRUE_VALUES = {"1", "true", "yes", "on"}
_SOURCE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_HEX_32 = re.compile(r"^[0-9a-fA-F]{64}$")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _parse_decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} is required")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be decimal-compatible") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{field} must be positive and finite")
    return parsed


def _load_key(path: Path) -> tuple[str, bytes]:
    if path.is_symlink():
        raise PermissionError("proposal key file cannot be a symlink")
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    source_id = values.get("BARRY_PROPOSAL_SOURCE_ID", "")
    secret_hex = values.get("BARRY_PROPOSAL_HMAC_KEY_HEX", "")
    if not _SOURCE_ID.fullmatch(source_id):
        raise ValueError("proposal source id is invalid")
    if not _HEX_32.fullmatch(secret_hex):
        raise ValueError("proposal HMAC key must be 32 bytes of hex")
    return source_id, bytes.fromhex(secret_hex)


def bridge_enabled() -> bool:
    return (
        os.getenv("BARRY_PHASE5_PROPOSALS_ENABLED", "false").strip().lower()
        in _TRUE_VALUES
    )


def build_shadow_payload(decision: dict[str, Any], now: datetime) -> dict[str, object]:
    if now.tzinfo is None:
        raise ValueError("proposal timestamp must be timezone-aware")
    symbol = str(decision.get("asset") or decision.get("symbol") or "BTC").upper()
    if not symbol.isalnum():
        raise ValueError("proposal symbol must use exchange notation")
    side = str(decision.get("action") or "").upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("proposal side must be LONG or SHORT")
    entry = _parse_decimal(decision.get("entry_price"), "entry_price")
    stop = _parse_decimal(decision.get("stop_loss"), "stop_loss")
    take_profit = _parse_decimal(decision.get("take_profit"), "take_profit")
    if side == "LONG" and not (stop < entry < take_profit):
        raise ValueError("LONG proposal requires stop_loss < entry_price < take_profit")
    if side == "SHORT" and not (take_profit < entry < stop):
        raise ValueError("SHORT proposal requires take_profit < entry_price < stop_loss")

    risk = Decimal(os.getenv("BARRY_PROPOSAL_REQUESTED_RISK_USD", "0.10"))
    if not risk.is_finite() or risk <= 0 or risk > Decimal("1.00"):
        raise ValueError("requested proposal risk must be positive and <= 1.00")
    expected_equity = Decimal(os.getenv("BARRY_PROPOSAL_EXPECTED_EQUITY_USD", "100"))
    if not expected_equity.is_finite() or expected_equity < 0:
        raise ValueError("expected proposal equity cannot be negative")
    signal_seed = _canonical(
        {
            "timestamp": decision.get("timestamp"),
            "symbol": symbol,
            "side": side,
            "entry": str(entry),
            "stop": str(stop),
            "take_profit": str(take_profit),
            "reasoning": decision.get("reasoning", ""),
        }
    )
    signal_id = hashlib.sha256(signal_seed.encode()).hexdigest()
    return {
        "proposal": {
            "client_request_id": str(uuid4()),
            "signal_id": str(uuid4()),
            "symbol": symbol,
            "side": side,
            "observed_at": now.astimezone(UTC).isoformat(),
            "entry_price": str(entry),
            "stop_loss": str(stop),
            "take_profit": str(take_profit),
            "requested_risk_usd": str(risk),
            "strategy": f"bastobot-v2-{signal_id[:12]}",
        },
        "expected_portfolio": {
            "equity_usd": str(expected_equity),
            "daily_realized_pnl_usd": "0",
            "exposure_by_symbol_usd": {},
        },
    }


def sign_payload(payload: dict[str, object], key_file: Path, now: datetime) -> dict[str, object]:
    if now.tzinfo is None:
        raise ValueError("proposal signing time must be timezone-aware")
    source_id, secret = _load_key(key_file)
    signed_at = now.astimezone(UTC)
    expires_at = signed_at + timedelta(seconds=300)
    nonce = f"{signed_at.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(12)}"
    payload_sha256 = hashlib.sha256(_canonical(payload).encode()).hexdigest()
    signing_message = _canonical(
        {
            "version": "barry-proposal-v1",
            "source_id": source_id,
            "nonce": nonce,
            "signed_at": signed_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "payload_sha256": payload_sha256,
        }
    )
    return {
        "version": "barry-proposal-v1",
        "source_id": source_id,
        "nonce": nonce,
        "signed_at": signed_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "payload": payload,
        "signature": hmac.new(secret, signing_message.encode(), hashlib.sha256).hexdigest(),
    }


def emit_phase5_proposal(decision: dict[str, Any]) -> Path | None:
    if not bridge_enabled():
        return None
    now = datetime.now(UTC)
    key_file = Path(
        os.getenv("BARRY_PROPOSAL_KEY_FILE", "/etc/barry/proposal-transport.env")
    )
    inbox = Path(os.getenv("BARRY_PHASE5_INBOX", "/var/spool/barry-phase5/inbox"))
    payload = build_shadow_payload(decision, now)
    signed = sign_payload(payload, key_file, now)
    inbox.mkdir(parents=True, exist_ok=True)
    target = inbox / f"{signed['source_id']}-{signed['nonce']}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(signed, indent=2, sort_keys=True))
    temporary.replace(target)
    return target
