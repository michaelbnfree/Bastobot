import pytest

from skills.active import hyperliquid as hl


# ── _sz_decimals / _sz_from_usd (network calls stubbed via _post) ──────────

def test_sz_decimals_returns_configured_value(monkeypatch):
    def fake_post(payload):
        assert payload == {"type": "meta"}
        return {"universe": [{"name": "BTC", "szDecimals": 5}, {"name": "ETH", "szDecimals": 4}]}

    monkeypatch.setattr(hl, "_post", fake_post)
    assert hl._sz_decimals("ETH") == 4


def test_sz_decimals_defaults_to_5_for_unknown_coin(monkeypatch):
    monkeypatch.setattr(hl, "_post", lambda payload: {"universe": []})
    assert hl._sz_decimals("NOPE") == 5


def test_sz_from_usd_converts_notional_to_coin_qty(monkeypatch):
    def fake_post(payload):
        if payload == {"type": "allMids"}:
            return {"BTC": "50000.0"}
        if payload == {"type": "meta"}:
            return {"universe": [{"name": "BTC", "szDecimals": 3}]}
        raise AssertionError(f"unexpected payload {payload}")

    monkeypatch.setattr(hl, "_post", fake_post)
    # $1000 notional at $50,000/BTC = 0.02 BTC, rounded to 3 decimals
    assert hl._sz_from_usd("BTC", 1000) == 0.02


def test_sz_from_usd_rounds_to_coin_precision(monkeypatch):
    def fake_post(payload):
        if payload == {"type": "allMids"}:
            return {"ETH": "3333.333"}
        if payload == {"type": "meta"}:
            return {"universe": [{"name": "ETH", "szDecimals": 2}]}
        raise AssertionError(f"unexpected payload {payload}")

    monkeypatch.setattr(hl, "_post", fake_post)
    assert hl._sz_from_usd("ETH", 100) == round(100 / 3333.333, 2)


def test_sz_from_usd_raises_when_no_mid_price(monkeypatch):
    monkeypatch.setattr(hl, "_post", lambda payload: {})
    with pytest.raises(ValueError, match="No mid price found for NOPE"):
        hl._sz_from_usd("NOPE", 100)


# ── get_all_mids ─────────────────────────────────────────────────────────────

def test_get_all_mids_filters_empty_string_values(monkeypatch):
    monkeypatch.setattr(hl, "_post", lambda payload: {"BTC": "50000.5", "MISSING": "", "ETH": "3000"})
    mids = hl.get_all_mids()
    assert mids == {"BTC": 50000.5, "ETH": 3000.0}
    assert "MISSING" not in mids


def test_get_all_mids_does_not_filter_string_zero(monkeypatch):
    """`if v` checks string truthiness, not the numeric value — "0" is a non-empty
    string and survives the filter as 0.0. Only an actual empty string is dropped."""
    monkeypatch.setattr(hl, "_post", lambda payload: {"BTC": "50000.5", "DEAD": "0"})
    mids = hl.get_all_mids()
    assert mids == {"BTC": 50000.5, "DEAD": 0.0}


# ── _parse_order_result ──────────────────────────────────────────────────────

def test_parse_order_result_returns_error_on_non_ok_status():
    result = {"status": "err", "response": "insufficient margin"}
    parsed = hl._parse_order_result(result, "BTC", "buy", 0.01)
    assert parsed == {"status": "err", "error": "insufficient margin"}


def test_parse_order_result_returns_error_from_status_entry():
    result = {"status": "ok", "response": {"data": {"statuses": [{"error": "Order would immediately match"}]}}}
    parsed = hl._parse_order_result(result, "BTC", "buy", 0.01)
    assert parsed == {"status": "err", "error": "Order would immediately match"}


def test_parse_order_result_filled_order():
    result = {
        "status": "ok",
        "response": {"data": {"statuses": [
            {"filled": {"oid": 123, "avgPx": "50123.456", "totalSz": "0.02"}}
        ]}},
    }
    parsed = hl._parse_order_result(result, "BTC", "buy", 0.02)
    assert parsed == {
        "status": "ok", "coin": "BTC", "side": "buy", "size": 0.02,
        "oid": 123, "filled_px": round(50123.456, 4),
        "filled_sz": 0.02,
    }


def test_parse_order_result_resting_limit_order():
    result = {
        "status": "ok",
        "response": {"data": {"statuses": [{"resting": {"oid": 456}}]}},
    }
    parsed = hl._parse_order_result(result, "ETH", "sell", 1.5, limit_px=3500.0)
    assert parsed == {
        "status": "ok", "coin": "ETH", "side": "sell", "size": 1.5,
        "limit_px": 3500.0, "oid": 456, "state": "resting",
    }


def test_parse_order_result_close_position_has_no_side_or_size():
    result = {
        "status": "ok",
        "response": {"data": {"statuses": [
            {"filled": {"oid": 789, "avgPx": "3000.0", "totalSz": "1.0"}}
        ]}},
    }
    parsed = hl._parse_order_result(result, "ETH", side=None, sz=None)
    assert "side" not in parsed
    assert "size" not in parsed
    assert parsed["filled_px"] == 3000.0
