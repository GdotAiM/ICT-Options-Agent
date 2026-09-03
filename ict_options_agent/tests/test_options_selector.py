"""
Unit tests for src/options_selector.py.

Strike/expiration selection logic is pure and testable against fake Alpaca
option contracts — no live API or network needed. We fake the TradingClient
at the level select_* actually calls it (client.get_option_contracts), so
the real GetOptionContractsRequest/ContractType/AssetStatus types are still
exercised exactly as in production.
"""
import pytest
pytest.importorskip("alpaca")

from types import SimpleNamespace
from alpaca.trading.enums import ContractType
from src.options_selector import (
    select_bull_call_spread,
    select_bear_put_spread,
    select_iron_condor,
)


def _contract(symbol, strike, exp="2026-09-19"):
    return SimpleNamespace(symbol=symbol, strike_price=str(strike), expiration_date=exp)


class FakeClient:
    """Stands in for alpaca.trading.client.TradingClient. Returns contracts
    filtered by the request's `type` field, mirroring what the real API does."""

    def __init__(self, calls=None, puts=None):
        self.calls = calls or []
        self.puts = puts or []

    def get_option_contracts(self, req):
        if req.type == ContractType.CALL:
            return SimpleNamespace(option_contracts=self.calls)
        return SimpleNamespace(option_contracts=self.puts)


# ---------------- select_bull_call_spread ----------------

def test_bull_call_spread_picks_nearest_entry_and_target_width():
    calls = [_contract(f"C{s}", s) for s in (495, 500, 505, 510, 515)]
    client = FakeClient(calls=calls)
    signal = {"underlying_price": 500, "entry_zone": 500}

    spread = select_bull_call_spread(client, "SPY", signal)

    assert spread is not None
    assert spread["type"] == "bull_call_spread"
    assert spread["long_strike"] == 500
    assert spread["short_strike"] == 505  # nearest to long+SPREAD_WIDTH_TARGET(5)
    assert spread["legs"][0]["side"] == "buy"
    assert spread["legs"][1]["side"] == "sell"


def test_bull_call_spread_no_contracts_returns_none():
    client = FakeClient(calls=[])
    signal = {"underlying_price": 500, "entry_zone": 500}
    assert select_bull_call_spread(client, "SPY", signal) is None


def test_bull_call_spread_single_contract_returns_none():
    client = FakeClient(calls=[_contract("C500", 500)])
    signal = {"underlying_price": 500, "entry_zone": 500}
    assert select_bull_call_spread(client, "SPY", signal) is None


def test_bull_call_spread_no_strikes_above_entry_returns_none():
    # only strikes at/below entry -> no valid short leg above the long leg
    calls = [_contract("C495", 495), _contract("C500", 500)]
    client = FakeClient(calls=calls)
    signal = {"underlying_price": 500, "entry_zone": 500}
    assert select_bull_call_spread(client, "SPY", signal) is None


def test_bull_call_spread_falls_back_to_underlying_price_without_entry_zone():
    calls = [_contract(f"C{s}", s) for s in (495, 500, 505)]
    client = FakeClient(calls=calls)
    signal = {"underlying_price": 500}  # no entry_zone key
    spread = select_bull_call_spread(client, "SPY", signal)
    assert spread is not None
    assert spread["long_strike"] == 500


# ---------------- select_bear_put_spread ----------------

def test_bear_put_spread_picks_nearest_entry_and_target_width():
    puts = [_contract(f"P{s}", s) for s in (485, 490, 495, 500, 505)]
    client = FakeClient(puts=puts)
    signal = {"underlying_price": 500, "entry_zone": 500}

    spread = select_bear_put_spread(client, "SPY", signal)

    assert spread is not None
    assert spread["type"] == "bear_put_spread"
    assert spread["long_strike"] == 500
    assert spread["short_strike"] == 495  # nearest to long-SPREAD_WIDTH_TARGET(5)
    assert spread["legs"][0]["side"] == "buy"
    assert spread["legs"][1]["side"] == "sell"


def test_bear_put_spread_no_contracts_returns_none():
    client = FakeClient(puts=[])
    signal = {"underlying_price": 500, "entry_zone": 500}
    assert select_bear_put_spread(client, "SPY", signal) is None


def test_bear_put_spread_no_strikes_below_entry_returns_none():
    puts = [_contract("P500", 500), _contract("P505", 505)]
    client = FakeClient(puts=puts)
    signal = {"underlying_price": 500, "entry_zone": 500}
    assert select_bear_put_spread(client, "SPY", signal) is None


# ---------------- select_iron_condor ----------------

def test_iron_condor_picks_expected_four_strikes():
    strikes = (480, 485, 490, 495, 500, 505, 510, 515, 520)
    calls = [_contract(f"C{s}", s) for s in strikes]
    puts = [_contract(f"P{s}", s) for s in strikes]
    client = FakeClient(calls=calls, puts=puts)
    signal = {"underlying_price": 500}

    condor = select_iron_condor(client, "SPY", signal)

    assert condor is not None
    assert condor["type"] == "iron_condor"
    # body=10 (2x default wing 5) -> short strikes at price +/- 5; wing=5 -> long strikes +/- 5 more
    assert condor["strikes"]["short_put"] == 495
    assert condor["strikes"]["long_put"] == 490
    assert condor["strikes"]["short_call"] == 505
    assert condor["strikes"]["long_call"] == 510
    assert len(condor["legs"]) == 4
    sides = [leg["side"] for leg in condor["legs"]]
    assert sides == ["buy", "sell", "sell", "buy"]  # long_put, short_put, short_call, long_call


def test_iron_condor_missing_calls_returns_none():
    puts = [_contract(f"P{s}", s) for s in (490, 495, 500, 505, 510)]
    client = FakeClient(calls=[], puts=puts)
    signal = {"underlying_price": 500}
    assert select_iron_condor(client, "SPY", signal) is None


def test_iron_condor_missing_puts_returns_none():
    calls = [_contract(f"C{s}", s) for s in (490, 495, 500, 505, 510)]
    client = FakeClient(calls=calls, puts=[])
    signal = {"underlying_price": 500}
    assert select_iron_condor(client, "SPY", signal) is None


def test_iron_condor_insufficient_strikes_one_side_returns_none():
    # only one put strike total -> can't form a put spread leg
    calls = [_contract(f"C{s}", s) for s in (490, 495, 500, 505, 510)]
    puts = [_contract("P500", 500)]
    client = FakeClient(calls=calls, puts=puts)
    signal = {"underlying_price": 500}
    assert select_iron_condor(client, "SPY", signal) is None


def test_iron_condor_selects_most_common_expiration():
    # majority of contracts share one expiry; a stray different-expiry
    # contract should be excluded from the selected chain
    strikes = (480, 485, 490, 495, 500, 505, 510, 515, 520)
    calls = [_contract(f"C{s}", s, exp="2026-09-19") for s in strikes]
    calls.append(_contract("C999", 999, exp="2026-10-17"))  # odd one out
    puts = [_contract(f"P{s}", s, exp="2026-09-19") for s in strikes]
    client = FakeClient(calls=calls, puts=puts)
    signal = {"underlying_price": 500}

    condor = select_iron_condor(client, "SPY", signal)
    assert condor is not None
    assert condor["expiration"] == "2026-09-19"
    used_symbols = {leg["symbol"] for leg in condor["legs"]}
    assert "C999" not in used_symbols
