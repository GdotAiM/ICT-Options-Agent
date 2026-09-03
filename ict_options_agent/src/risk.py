"""
Position sizing, risk guards, and deterministic exit decisions.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Any, Optional, Tuple
from loguru import logger
from config.settings import (
    RISK_PCT,
    MAX_CONTRACTS_PER_TRADE,
    MAX_POSITIONS,
    MAX_DAILY_LOSS_PCT,
    PROFIT_TARGET_PCT,
    STOP_LOSS_PCT,
    MAX_DTE_TO_HOLD,
)


def check_daily_kill_switch(starting_equity: float, current_equity: float) -> Tuple[bool, str]:
    """
    Returns (breached, reason). breached=True means: halt all new entries
    for the rest of the day. Compares current account equity (which reflects
    both realized and unrealized P&L) against the day's starting equity —
    simpler and more robust than trying to attribute P&L per closed trade.
    """
    if starting_equity <= 0:
        return False, ""
    drawdown_pct = (current_equity - starting_equity) / starting_equity
    if drawdown_pct <= -abs(MAX_DAILY_LOSS_PCT):
        reason = (
            f"Daily drawdown {drawdown_pct:.2%} breached max "
            f"-{MAX_DAILY_LOSS_PCT:.2%} (start ${starting_equity:,.2f} -> "
            f"now ${current_equity:,.2f})"
        )
        return True, reason
    return False, ""


def calculate_contracts(equity: float, max_loss_per_contract: float, risk_pct: float = RISK_PCT) -> int:
    """
    max_loss_per_contract is in dollars (e.g. net debit * 100).
    """
    if max_loss_per_contract <= 0 or equity <= 0:
        return 0
    risk_dollars = equity * risk_pct
    qty = int(risk_dollars / max_loss_per_contract)
    qty = max(0, min(qty, MAX_CONTRACTS_PER_TRADE))
    return qty


def can_open_new_position(current_positions: int) -> bool:
    return current_positions < MAX_POSITIONS


def approximate_debit(long_mid: float, short_mid: float) -> float:
    """Net debit for a debit spread (positive number)."""
    return max(0.01, long_mid - short_mid)


# ---------------------------------------------------------------------------
# Exit helpers
# ---------------------------------------------------------------------------

def parse_option_expiration(symbol: str) -> Optional[date]:
    """
    Parse OCC option symbol → expiration date.
    Format: ROOT + YYMMDD + C/P + strike (e.g. SPY250919C00450000).
    Root can be 1–6 letters; we scan for the 6-digit date that is followed
    by C or P.
    """
    if not symbol or len(symbol) < 15:
        return None
    # Find the first occurrence of 6 digits followed by C or P
    for i in range(len(symbol) - 6):
        chunk = symbol[i : i + 6]
        if chunk.isdigit():
            suffix = symbol[i + 6 : i + 7]
            if suffix in ("C", "P", "c", "p"):
                try:
                    yy, mm, dd = int(chunk[0:2]), int(chunk[2:4]), int(chunk[4:6])
                    # Alpaca uses 2-digit year; assume 2000–2099
                    year = 2000 + yy if yy < 100 else yy
                    return date(year, mm, dd)
                except ValueError:
                    continue
    return None


def days_to_expiration(symbol: str, today: Optional[date] = None) -> Optional[int]:
    exp = parse_option_expiration(symbol)
    if exp is None:
        return None
    today = today or date.today()
    return (exp - today).days


def should_close_position(
    pos: Any,
    profit_target_pct: float = PROFIT_TARGET_PCT,
    stop_loss_pct: float = STOP_LOSS_PCT,
    max_dte_to_hold: int = MAX_DTE_TO_HOLD,
    today: Optional[date] = None,
) -> Tuple[bool, str]:
    """
    Deterministic exit decision for a single Alpaca Position (or duck-typed
    object with .symbol, .unrealized_plpc, .asset_class / .qty).

    Returns (should_close, reason).
    Only considers option positions; equity positions are ignored.
    """
    symbol = getattr(pos, "symbol", "") or ""
    asset_class = str(getattr(pos, "asset_class", "") or "").lower()
    # Alpaca marks options as "us_option"; also accept symbols that look like OCC
    is_option = asset_class in ("us_option", "option") or (
        len(symbol) >= 15 and any(c in symbol for c in ("C", "P"))
    )
    if not is_option:
        return False, ""

    # --- DTE gate ---
    dte = days_to_expiration(symbol, today=today)
    if dte is not None and dte <= max_dte_to_hold:
        return True, f"DTE={dte} <= max_hold={max_dte_to_hold}"

    # --- P&L gates (unrealized_plpc is already a fraction, e.g. 0.42 = +42%) ---
    try:
        plpc = float(getattr(pos, "unrealized_plpc", 0) or 0)
    except (TypeError, ValueError):
        plpc = 0.0

    if plpc >= profit_target_pct:
        return True, f"profit target hit ({plpc:.1%} >= {profit_target_pct:.0%})"
    if plpc <= stop_loss_pct:
        return True, f"stop loss hit ({plpc:.1%} <= {stop_loss_pct:.0%})"

    return False, ""


def estimate_position_risk_dollars(pos) -> float:
    """
    Estimate dollars at risk for one option position.

    For debit spreads (bull call, bear put): max loss = premium paid = cost_basis.
    For credit spreads (iron condor): max loss = wing_width * 100 - credit_received.
      Alpaca's Position object does not carry wing-width metadata, so we conservatively
      estimate condor risk as abs(market_value) when cost_basis is small (credit received)
      and market_value is large (the wing represents the true max-loss exposure).
      This is an approximation — the exact value requires storing leg composition at
      order time (see state_store legs_json) and recomputing there.
    """
    try:
        cost = abs(float(getattr(pos, "cost_basis", 0) or 0))
        mv = abs(float(getattr(pos, "market_value", 0) or 0))
        # Heuristic: if cost_basis is very small relative to market_value, this is
        # likely a credit strategy (iron condor) where cost_basis ≈ net credit received.
        # Use market_value as a conservative proxy for max loss in that case.
        if cost > 0 and mv / cost > 5.0:
            return mv
        return max(cost, mv)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def portfolio_risk_dollars(positions) -> float:
    return sum(estimate_position_risk_dollars(p) for p in positions)


def portfolio_risk_pct(positions, equity: float) -> float:
    if equity <= 0:
        return 0.0
    return portfolio_risk_dollars(positions) / equity


def can_add_risk(
    positions,
    equity: float,
    additional_risk: float,
    max_pct: float = None,
) -> tuple:
    """
    Returns (ok, reason). Blocks a new trade if total risk would exceed
    MAX_PORTFOLIO_RISK_PCT of equity.
    """
    from config.settings import MAX_PORTFOLIO_RISK_PCT
    max_pct = MAX_PORTFOLIO_RISK_PCT if max_pct is None else max_pct
    current = portfolio_risk_dollars(positions)
    projected = current + max(0.0, additional_risk)
    if equity <= 0:
        return False, "equity <= 0"
    if projected / equity > max_pct:
        return False, (
            f"portfolio risk ${projected:,.0f} would be "
            f"{projected/equity:.1%} of equity (max {max_pct:.1%})"
        )
    return True, ""


def estimate_portfolio_delta(positions) -> float:
    """
    Sum signed deltas if present on position objects; otherwise 0.
    Alpaca Position may not always expose greeks — treat missing as 0.
    """
    total = 0.0
    for pos in positions:
        try:
            d = getattr(pos, "delta", None)
            if d is None:
                # some SDKs nest under .greeks
                g = getattr(pos, "greeks", None)
                d = getattr(g, "delta", 0) if g else 0
            qty = float(getattr(pos, "qty", 0) or 0)
            total += float(d or 0) * qty
        except (TypeError, ValueError):
            continue
    return total


def delta_within_limit(positions, max_delta: float = None) -> tuple:
    from config.settings import MAX_PORTFOLIO_DELTA
    max_delta = MAX_PORTFOLIO_DELTA if max_delta is None else max_delta
    if not max_delta or max_delta <= 0:
        return True, ""
    d = estimate_portfolio_delta(positions)
    if abs(d) > max_delta:
        return False, f"portfolio delta {d:.1f} exceeds ±{max_delta}"
    return True, ""
