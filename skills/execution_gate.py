"""Fail-closed exchange mutation gate for the BastoBot interface layer.

BastoBot may read market/account state, but it must not place, change, cancel,
or close exchange orders unless an operator deliberately enables mutations.
The canonical Barry execution service will eventually own that authority.
"""

import os


_TRUE_VALUES = {"1", "true", "yes", "on"}


def exchange_mutations_enabled() -> bool:
    """Return True only for an explicit operator opt-in."""
    return os.getenv("BASTOBOT_EXCHANGE_MUTATIONS_ENABLED", "false").strip().lower() in _TRUE_VALUES


def require_exchange_mutations_enabled() -> None:
    """Raise before any exchange-mutating call when containment is active."""
    if not exchange_mutations_enabled():
        raise PermissionError(
            "BastoBot exchange mutations are disabled. "
            "Route execution through the canonical Barry engine."
        )
