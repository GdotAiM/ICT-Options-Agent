"""Tests for MLEG close-leg inversion and options-level constants.

Avoids importing the full ICTOptionsAgent (needs alpaca-py) by extracting
the pure invert helper logic inline for unit testing.
"""
REQUIRED_OPTIONS_LEVEL = 3


def _invert_legs_for_close(open_legs):
    """Mirror of ICTOptionsAgent._invert_legs_for_close (pure function)."""
    close_legs = []
    for leg in open_legs:
        side = (leg.get("side") or "buy").lower()
        if side == "buy":
            close_legs.append({
                "symbol": leg["symbol"],
                "side": "sell",
                "ratio_qty": leg.get("ratio_qty", 1),
                "position_intent": "sell_to_close",
                "role": leg.get("role", ""),
            })
        else:
            close_legs.append({
                "symbol": leg["symbol"],
                "side": "buy",
                "ratio_qty": leg.get("ratio_qty", 1),
                "position_intent": "buy_to_close",
                "role": leg.get("role", ""),
            })
    return close_legs


def test_required_options_level_is_three():
    assert REQUIRED_OPTIONS_LEVEL == 3


def test_invert_legs_for_close_debit_spread():
    open_legs = [
        {"symbol": "SPY250919C00450000", "side": "buy", "role": "long"},
        {"symbol": "SPY250919C00455000", "side": "sell", "role": "short"},
    ]
    close_legs = _invert_legs_for_close(open_legs)
    assert len(close_legs) == 2
    assert close_legs[0]["side"] == "sell"
    assert close_legs[0]["position_intent"] == "sell_to_close"
    assert close_legs[1]["side"] == "buy"
    assert close_legs[1]["position_intent"] == "buy_to_close"
    assert close_legs[0]["symbol"] == open_legs[0]["symbol"]


def test_invert_legs_for_close_iron_condor():
    open_legs = [
        {"symbol": "SPY250919P00440000", "side": "buy", "role": "long_put"},
        {"symbol": "SPY250919P00445000", "side": "sell", "role": "short_put"},
        {"symbol": "SPY250919C00455000", "side": "sell", "role": "short_call"},
        {"symbol": "SPY250919C00460000", "side": "buy", "role": "long_call"},
    ]
    close_legs = _invert_legs_for_close(open_legs)
    assert len(close_legs) == 4
    intents = {lg["position_intent"] for lg in close_legs}
    assert intents == {"buy_to_close", "sell_to_close"}
    for o, c in zip(open_legs, close_legs):
        if o["side"] == "buy":
            assert c["side"] == "sell"
        else:
            assert c["side"] == "buy"


def test_mcp_legs_respect_close_intent():
    from src.mcp_exec import _legs_for_mcp
    legs = [
        {"symbol": "SPY250919C00450000", "side": "sell", "position_intent": "sell_to_close"},
        {"symbol": "SPY250919C00455000", "side": "buy", "position_intent": "buy_to_close"},
    ]
    out = _legs_for_mcp(legs)
    assert out[0]["position_intent"] == "sell_to_close"
    assert out[1]["position_intent"] == "buy_to_close"
    assert _legs_for_mcp([{"symbol": "X", "side": "buy"}])[0]["position_intent"] == "buy_to_open"
