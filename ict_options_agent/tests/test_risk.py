"""Unit tests for src/risk.py — position sizing, caps, kill switch, and exits."""
from datetime import date
from types import SimpleNamespace
from src.risk import (
    calculate_contracts,
    can_open_new_position,
    approximate_debit,
    check_daily_kill_switch,
    parse_option_expiration,
    days_to_expiration,
    should_close_position,
    estimate_position_risk_dollars,
)
from config.settings import (
    MAX_CONTRACTS_PER_TRADE,
    MAX_POSITIONS,
    MAX_DAILY_LOSS_PCT,
    PROFIT_TARGET_PCT,
    STOP_LOSS_PCT,
    MAX_DTE_TO_HOLD,
)


# ---------------- calculate_contracts ----------------

def test_calculate_contracts_normal_case():
    # equity=100k, risk_pct=0.0075 -> risk_dollars=750; max_loss_per_contract=125
    qty = calculate_contracts(100_000, 125, risk_pct=0.0075)
    assert qty == 6  # 750 / 125 = 6.0


def test_calculate_contracts_zero_loss_per_contract_returns_zero():
    assert calculate_contracts(100_000, 0, risk_pct=0.01) == 0


def test_calculate_contracts_negative_loss_per_contract_returns_zero():
    assert calculate_contracts(100_000, -50, risk_pct=0.01) == 0


def test_calculate_contracts_zero_equity_returns_zero():
    assert calculate_contracts(0, 100, risk_pct=0.01) == 0


def test_calculate_contracts_negative_equity_returns_zero():
    assert calculate_contracts(-500, 100, risk_pct=0.01) == 0


def test_calculate_contracts_caps_at_max_contracts_per_trade():
    # huge equity, tiny loss-per-contract -> would size way past the cap
    qty = calculate_contracts(1_000_000, 1, risk_pct=1.0)
    assert qty == MAX_CONTRACTS_PER_TRADE


def test_calculate_contracts_rounds_down_never_up():
    # risk_dollars = 100_000 * 0.01 = 1000; 1000/300 = 3.33 -> must floor to 3
    qty = calculate_contracts(100_000, 300, risk_pct=0.01)
    assert qty == 3


def test_calculate_contracts_never_negative():
    qty = calculate_contracts(100_000, 10_000_000, risk_pct=0.0001)
    assert qty >= 0


# ---------------- can_open_new_position ----------------

def test_can_open_new_position_under_cap():
    assert can_open_new_position(MAX_POSITIONS - 1) is True


def test_can_open_new_position_at_cap_blocks():
    assert can_open_new_position(MAX_POSITIONS) is False


def test_can_open_new_position_over_cap_blocks():
    assert can_open_new_position(MAX_POSITIONS + 5) is False


def test_can_open_new_position_zero_positions():
    assert can_open_new_position(0) is True


# ---------------- approximate_debit ----------------

def test_approximate_debit_normal():
    assert approximate_debit(long_mid=3.50, short_mid=1.75) == 1.75


def test_approximate_debit_floors_at_one_cent_when_inverted():
    # short_mid > long_mid shouldn't produce a negative/zero debit
    assert approximate_debit(long_mid=1.0, short_mid=2.0) == 0.01


# ---------------- check_daily_kill_switch ----------------

def test_kill_switch_not_breached_small_drawdown():
    breached, reason = check_daily_kill_switch(100_000, 98_500)  # -1.5%
    assert breached is False
    assert reason == ""


def test_kill_switch_breached_at_exact_threshold():
    threshold_equity = 100_000 * (1 - MAX_DAILY_LOSS_PCT)
    breached, reason = check_daily_kill_switch(100_000, threshold_equity)
    assert breached is True
    assert "breached" in reason


def test_kill_switch_just_under_threshold_not_breached():
    # one cent better than the exact threshold should NOT trip
    threshold_equity = 100_000 * (1 - MAX_DAILY_LOSS_PCT) + 1
    breached, _ = check_daily_kill_switch(100_000, threshold_equity)
    assert breached is False


def test_kill_switch_profit_day_never_breaches():
    breached, reason = check_daily_kill_switch(100_000, 150_000)
    assert breached is False
    assert reason == ""


def test_kill_switch_zero_starting_equity_never_breaches():
    # guards against a div-by-zero if equity fetch ever returns 0 on init
    breached, reason = check_daily_kill_switch(0, 0)
    assert breached is False


def test_kill_switch_reason_includes_actual_numbers():
    breached, reason = check_daily_kill_switch(100_000, 90_000)
    assert breached is True
    assert "100,000.00" in reason
    assert "90,000.00" in reason


# ---------------- parse_option_expiration / days_to_expiration ----------------

def test_parse_option_expiration_standard_spy():
    exp = parse_option_expiration("SPY250919C00450000")
    assert exp == date(2025, 9, 19)


def test_parse_option_expiration_put():
    exp = parse_option_expiration("QQQ260320P00380000")
    assert exp == date(2026, 3, 20)


def test_parse_option_expiration_short_root():
    exp = parse_option_expiration("AAPL251219C00200000")
    assert exp == date(2025, 12, 19)


def test_parse_option_expiration_invalid_returns_none():
    assert parse_option_expiration("SPY") is None
    assert parse_option_expiration("") is None
    assert parse_option_expiration("NOTANOPTION") is None


def test_days_to_expiration_future():
    # fixed "today" so the test is deterministic
    dte = days_to_expiration("SPY250919C00450000", today=date(2025, 9, 10))
    assert dte == 9


def test_days_to_expiration_past_or_today():
    dte = days_to_expiration("SPY250910C00450000", today=date(2025, 9, 10))
    assert dte == 0


# ---------------- should_close_position ----------------

def _opt_pos(symbol, plpc, asset_class="us_option"):
    return SimpleNamespace(
        symbol=symbol,
        unrealized_plpc=plpc,
        asset_class=asset_class,
        qty=1,
    )


def test_should_close_profit_target():
    pos = _opt_pos("SPY251219C00450000", plpc=0.55)
    should, reason = should_close_position(pos, today=date(2025, 9, 1))
    assert should is True
    assert "profit target" in reason


def test_should_close_stop_loss():
    pos = _opt_pos("SPY251219C00450000", plpc=-1.05)
    should, reason = should_close_position(pos, today=date(2025, 9, 1))
    assert should is True
    assert "stop loss" in reason


def test_should_close_low_dte():
    # expiration 2025-09-12, today 2025-09-11 → DTE=1 <= default MAX_DTE_TO_HOLD=2
    pos = _opt_pos("SPY250912C00450000", plpc=0.10)
    should, reason = should_close_position(pos, today=date(2025, 9, 11))
    assert should is True
    assert "DTE=" in reason


def test_should_not_close_healthy_position():
    pos = _opt_pos("SPY251219C00450000", plpc=0.20)
    should, reason = should_close_position(pos, today=date(2025, 9, 1))
    assert should is False
    assert reason == ""


def test_should_not_close_equity_position():
    pos = SimpleNamespace(
        symbol="SPY",
        unrealized_plpc=0.80,
        asset_class="us_equity",
        qty=10,
    )
    should, reason = should_close_position(pos, today=date(2025, 9, 1))
    assert should is False


def test_should_close_respects_custom_thresholds():
    pos = _opt_pos("SPY251219C00450000", plpc=0.30)
    should, _ = should_close_position(
        pos, profit_target_pct=0.25, stop_loss_pct=-2.0, today=date(2025, 9, 1)
    )
    assert should is True


# (exit helpers already covered above)


# ---------------- portfolio risk helpers ----------------

def test_portfolio_risk_pct_empty():
    from src.risk import portfolio_risk_pct
    assert portfolio_risk_pct([], 100_000) == 0.0


def test_can_add_risk_blocks_when_over_cap():
    from src.risk import can_add_risk
    from types import SimpleNamespace
    # existing position with $3k risk; equity 100k; max 4% = $4k
    pos = SimpleNamespace(cost_basis=3000, market_value=3000)
    ok, reason = can_add_risk([pos], 100_000, additional_risk=1500, max_pct=0.04)
    assert ok is False
    assert "portfolio risk" in reason


def test_can_add_risk_allows_under_cap():
    from src.risk import can_add_risk
    from types import SimpleNamespace
    pos = SimpleNamespace(cost_basis=1000, market_value=1000)
    ok, reason = can_add_risk([pos], 100_000, additional_risk=500, max_pct=0.04)
    assert ok is True
    assert reason == ""


def test_delta_within_limit_off_when_zero():
    from src.risk import delta_within_limit
    ok, _ = delta_within_limit([], max_delta=0)
    assert ok is True


# ---------------- estimate_position_risk_dollars ----------------

def test_estimate_position_risk_debit_spread_uses_cost_basis():
    """For a debit spread, cost_basis ≈ premium paid = true max loss."""
    pos = SimpleNamespace(cost_basis=500, market_value=320)
    assert estimate_position_risk_dollars(pos) == 500


def test_estimate_position_risk_condor_heuristic_returns_market_value():
    """When cost_basis is tiny relative to market_value (credit-strategy
    signature), use market_value as a conservative proxy for wing-width risk.
    An iron condor's cost_basis is the net credit received — far smaller than
    the actual max loss (wing width × 100)."""
    # Typical iron condor: credit received $0.30 × 100 = $30 cost_basis,
    # but market_value could be $400 if the position moved against us.
    pos = SimpleNamespace(cost_basis=30, market_value=400)
    assert estimate_position_risk_dollars(pos) == 400


def test_estimate_position_risk_falls_back_on_zero():
    pos = SimpleNamespace()  # no cost_basis, no market_value attrs
    assert estimate_position_risk_dollars(pos) == 0.0


def test_estimate_position_risk_handles_missing_attrs_gracefully():
    pos = SimpleNamespace(foo="bar")
    assert estimate_position_risk_dollars(pos) == 0.0
