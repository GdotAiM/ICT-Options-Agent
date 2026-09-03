"""
Unit tests for src/quotes.py — quote quality gates (staleness, wide spreads,
crossed/empty quotes) and the net_debit_credit / iron_condor_credit pricing
functions built on top of them.

Quotes are faked as plain dicts (bp/ap/t keys) so no live API/network is
needed, exercising the exact dict-fallback path evaluate_quote() supports
for the {"bp":..., "ap":...} shape some Alpaca responses use.
"""
import pytest
pytest.importorskip("alpaca")

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import src.quotes as quotes


def _obj_quote(bid, ask, age_seconds=0):
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return SimpleNamespace(bid_price=bid, ask_price=ask, timestamp=ts)


def _dict_quote(bid, ask, age_seconds=0):
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return {"bp": bid, "ap": ask, "t": ts.isoformat()}


# ---------------- evaluate_quote: normal cases ----------------

def test_evaluate_quote_normal_tight_spread_ok():
    q = _obj_quote(bid=1.20, ask=1.25)
    ok, mid, reason = quotes.evaluate_quote(q)
    assert ok is True
    assert mid == 1.225
    assert reason == ""


def test_evaluate_quote_dict_shaped_quote_ok():
    q = _dict_quote(bid=2.00, ask=2.10)
    ok, mid, reason = quotes.evaluate_quote(q)
    assert ok is True
    assert abs(mid - 2.05) < 1e-9


def test_evaluate_quote_ask_only_uses_ask_as_mid():
    q = _obj_quote(bid=0, ask=1.50)
    ok, mid, reason = quotes.evaluate_quote(q)
    assert ok is True
    assert mid == 1.50


def test_evaluate_quote_bid_only_uses_bid_as_mid():
    q = _obj_quote(bid=0.90, ask=0)
    ok, mid, reason = quotes.evaluate_quote(q)
    assert ok is True
    assert mid == 0.90


# ---------------- evaluate_quote: rejection cases ----------------

def test_evaluate_quote_no_bid_or_ask_rejected():
    q = _obj_quote(bid=0, ask=0)
    ok, mid, reason = quotes.evaluate_quote(q)
    assert ok is False
    assert mid is None
    assert "no bid or ask" in reason


def test_evaluate_quote_crossed_market_rejected():
    q = _obj_quote(bid=2.00, ask=1.50)  # bid > ask: broken/crossed
    ok, mid, reason = quotes.evaluate_quote(q)
    assert ok is False
    assert "crossed" in reason


def test_evaluate_quote_wide_spread_rejected():
    # mid=1.00, spread=0.60 -> 60% of mid, well over default 25% max
    q = _obj_quote(bid=0.70, ask=1.30)
    ok, mid, reason = quotes.evaluate_quote(q, max_spread_pct=0.25)
    assert ok is False
    assert mid == 1.00  # mid still reported for logging even though rejected
    assert "spread" in reason and "wide" in reason


def test_evaluate_quote_spread_exactly_at_threshold_is_ok():
    # spread/mid exactly 0.25 should pass (not '>')
    q = _obj_quote(bid=0.875, ask=1.125)  # mid=1.0, spread=0.25 -> 25.0%
    ok, mid, reason = quotes.evaluate_quote(q, max_spread_pct=0.25)
    assert ok is True


def test_evaluate_quote_stale_quote_rejected():
    q = _obj_quote(bid=1.0, ask=1.05, age_seconds=120)
    ok, mid, reason = quotes.evaluate_quote(q, max_age_seconds=30)
    assert ok is False
    assert "stale" in reason


def test_evaluate_quote_fresh_quote_within_max_age_ok():
    q = _obj_quote(bid=1.0, ask=1.05, age_seconds=5)
    ok, mid, reason = quotes.evaluate_quote(q, max_age_seconds=30)
    assert ok is True


def test_evaluate_quote_missing_timestamp_not_treated_as_stale():
    q = SimpleNamespace(bid_price=1.0, ask_price=1.05)  # no timestamp at all
    ok, mid, reason = quotes.evaluate_quote(q, max_age_seconds=30)
    assert ok is True  # absence of data isn't proof of staleness


def test_evaluate_quote_unparseable_bid_ask_rejected():
    q = SimpleNamespace(bid_price="not-a-number", ask_price="also-bad")
    ok, mid, reason = quotes.evaluate_quote(q)
    assert ok is False
    assert "unparseable" in reason


# ---------------- quote_age_seconds ----------------

def test_quote_age_seconds_computes_positive_age():
    q = _obj_quote(bid=1.0, ask=1.05, age_seconds=45)
    age = quotes.quote_age_seconds(q)
    assert age is not None
    assert 40 <= age <= 50


def test_quote_age_seconds_none_when_no_timestamp():
    q = SimpleNamespace(bid_price=1.0, ask_price=1.05)
    assert quotes.quote_age_seconds(q) is None


def test_quote_age_seconds_handles_naive_datetime_as_utc():
    # Construct a naive timestamp 10 seconds in the past so the assertion
    # holds regardless of machine timezone or wall-clock time.
    naive_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=10)  # no tzinfo
    q = SimpleNamespace(bid_price=1.0, ask_price=1.10, timestamp=naive_ts)
    age = quotes.quote_age_seconds(q)
    assert age is not None
    # Function treats naive timestamps as UTC; age should be ~10s.
    assert 5 <= age <= 20


# ---------------- net_debit_credit ----------------

def test_net_debit_credit_normal_case(monkeypatch):
    fake_quotes = {
        "LONG": _obj_quote(bid=3.00, ask=3.10),
        "SHORT": _obj_quote(bid=1.00, ask=1.10),
    }
    monkeypatch.setattr(quotes, "get_latest_quotes", lambda symbols: fake_quotes)
    net, long_mid, short_mid, reason = quotes.net_debit_credit("LONG", "SHORT")
    assert net is not None
    assert round(net, 2) == round(3.05 - 1.05, 2)
    assert reason == ""


def test_net_debit_credit_missing_leg_returns_none_with_reason(monkeypatch):
    monkeypatch.setattr(quotes, "get_latest_quotes", lambda symbols: {"LONG": _obj_quote(3.0, 3.1)})
    net, long_mid, short_mid, reason = quotes.net_debit_credit("LONG", "SHORT")
    assert net is None
    assert "missing" in reason


def test_net_debit_credit_wide_short_leg_rejects_whole_pair(monkeypatch):
    fake_quotes = {
        "LONG": _obj_quote(bid=3.00, ask=3.10),          # fine
        "SHORT": _obj_quote(bid=0.50, ask=1.50),          # 100% spread - too wide
    }
    monkeypatch.setattr(quotes, "get_latest_quotes", lambda symbols: fake_quotes)
    net, long_mid, short_mid, reason = quotes.net_debit_credit("LONG", "SHORT")
    assert net is None
    assert "SHORT" in reason


def test_net_debit_credit_stale_long_leg_rejects_whole_pair(monkeypatch):
    fake_quotes = {
        "LONG": _obj_quote(bid=3.00, ask=3.10, age_seconds=999),
        "SHORT": _obj_quote(bid=1.00, ask=1.10),
    }
    monkeypatch.setattr(quotes, "get_latest_quotes", lambda symbols: fake_quotes)
    net, long_mid, short_mid, reason = quotes.net_debit_credit("LONG", "SHORT")
    assert net is None
    assert "LONG" in reason and "stale" in reason


# ---------------- iron_condor_credit ----------------

def test_iron_condor_credit_normal_case(monkeypatch):
    fake_quotes = {
        "LP": _obj_quote(bid=1.00, ask=1.10),
        "SP": _obj_quote(bid=2.00, ask=2.10),
        "SC": _obj_quote(bid=2.00, ask=2.10),
        "LC": _obj_quote(bid=1.00, ask=1.10),
    }
    monkeypatch.setattr(quotes, "get_latest_quotes", lambda symbols: fake_quotes)
    credit, mids, reason = quotes.iron_condor_credit("LP", "SP", "SC", "LC")
    assert credit is not None
    assert credit > 0
    assert reason == ""
    assert set(mids.keys()) == {"LP", "SP", "SC", "LC"}


def test_iron_condor_credit_one_bad_leg_rejects_whole_condor(monkeypatch):
    fake_quotes = {
        "LP": _obj_quote(bid=1.00, ask=1.10),
        "SP": _obj_quote(bid=0, ask=0),  # dead quote
        "SC": _obj_quote(bid=2.00, ask=2.10),
        "LC": _obj_quote(bid=1.00, ask=1.10),
    }
    monkeypatch.setattr(quotes, "get_latest_quotes", lambda symbols: fake_quotes)
    credit, mids, reason = quotes.iron_condor_credit("LP", "SP", "SC", "LC")
    assert credit is None
    assert mids == {}
    assert "SP" in reason


def test_iron_condor_credit_missing_symbol_in_response(monkeypatch):
    fake_quotes = {
        "LP": _obj_quote(bid=1.00, ask=1.10),
        "SP": _obj_quote(bid=2.00, ask=2.10),
        "SC": _obj_quote(bid=2.00, ask=2.10),
        # LC missing entirely
    }
    monkeypatch.setattr(quotes, "get_latest_quotes", lambda symbols: fake_quotes)
    credit, mids, reason = quotes.iron_condor_credit("LP", "SP", "SC", "LC")
    assert credit is None
    assert "LC" in reason and "missing" in reason


# ---------------- mid_price backward-compat shim ----------------

def test_mid_price_still_works_without_quality_gate():
    # even a wide/stale quote should still report a mid via the legacy helper
    q = _obj_quote(bid=0.50, ask=1.50, age_seconds=999)
    assert quotes.mid_price(q) == 1.00
