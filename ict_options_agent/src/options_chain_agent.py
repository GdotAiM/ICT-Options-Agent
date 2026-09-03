"""Options-chain intelligence for the ICT AI agent.

This module does not place orders. It turns the live Alpaca option chain and
quotes into a compact, model-readable decision surface: DTE, moneyness,
liquidity, bid/ask quality, IV/Greeks when available, and candidate spreads.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List
from collections import Counter

from loguru import logger

from config import settings
from src.options_selector import get_option_contracts
from src.quotes import get_latest_quotes, get_option_snapshots, evaluate_quote


def _num(v, default=None):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _attr(obj, *names):
    for name in names:
        v = getattr(obj, name, None)
        if v is not None:
            return v
        if hasattr(obj, "get"):
            v = obj.get(name)
            if v is not None:
                return v
    return None


def _expiry_str(c):
    e = _attr(c, "expiration_date")
    return str(e)[:10] if e else None


def _dte(exp):
    try:
        return max(0, (datetime.fromisoformat(str(exp)).date() - datetime.now().date()).days)
    except Exception:
        return None


def _candidate_rows(contracts: List[Any], price: float, expiry: str, quotes: Dict[str, Any], snapshots: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for c in contracts:
        if _expiry_str(c) != expiry or _attr(c, "strike_price") is None:
            continue
        strike = _num(_attr(c, "strike_price"))
        if strike is None or strike <= 0:
            continue
        # Keep a useful but bounded neighborhood around spot.
        if price and abs(strike / price - 1.0) > 0.12:
            continue
        sym = _attr(c, "symbol")
        q = quotes.get(sym) if sym else None
        snap = snapshots.get(sym) if sym else None
        row = {
            "symbol": sym,
            "strike": strike,
            "type": str(_attr(c, "type") or ""),
            "expiration": expiry,
            "dte": _dte(expiry),
            "open_interest": _num(_attr(c, "open_interest"), 0),
            "volume": _num(_attr(c, "volume"), 0),
            "moneyness_pct": round((strike / price - 1.0) * 100, 3) if price else None,
        }
        if snap is not None:
            row["implied_volatility"] = _num(_attr(snap, "implied_volatility", "iv"))
            greeks = _attr(snap, "greeks")
            if greeks is not None:
                row["greeks"] = {k: _num(_attr(greeks, k)) for k in ("delta", "gamma", "theta", "vega", "rho") if _attr(greeks, k) is not None}
        if q is not None:
            ok, mid, reason = evaluate_quote(q)
            bid = _num(_attr(q, "bid_price", "bp"), 0)
            ask = _num(_attr(q, "ask_price", "ap"), 0)
            row.update({
                "bid": bid, "ask": ask, "mid": mid,
                "quote_ok": ok, "quote_reason": reason,
                "spread_pct": round((ask - bid) / ((ask + bid) / 2) * 100, 2) if bid > 0 and ask > 0 else None,
            })
        rows.append(row)
    rows.sort(key=lambda r: abs(r["moneyness_pct"] or 0))
    return rows[:24]


def build_options_chain_evidence(client, underlying: str, signal: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch and summarize the live chain for AI structure selection."""
    price = _num(signal.get("underlying_price"), 0.0)
    try:
        calls = get_option_contracts(client, underlying, __import__("alpaca.trading.enums", fromlist=["ContractType"]).ContractType.CALL)
        puts = get_option_contracts(client, underlying, __import__("alpaca.trading.enums", fromlist=["ContractType"]).ContractType.PUT)
    except Exception as e:
        logger.warning(f"Options chain fetch failed for {underlying}: {e}")
        return {"available": False, "reason": str(e), "underlying": underlying}

    expiries = Counter([_expiry_str(c) for c in calls + puts if _expiry_str(c)])
    if not expiries:
        return {"available": False, "reason": "no active option expirations", "underlying": underlying}

    target_dte = int(signal.get("ai_options_dte_target") or 7)
    valid = []
    for exp in expiries:
        dte = _dte(exp)
        if dte is not None and settings.MIN_DTE <= dte <= settings.MAX_DTE:
            valid.append((abs(dte - target_dte), -expiries[exp], exp))
    if not valid:
        return {"available": False, "reason": "no expiration inside configured DTE window", "underlying": underlying}
    valid.sort()
    expiry = valid[0][2]

    symbols = [
        _attr(c, "symbol") for c in calls + puts
        if _expiry_str(c) == expiry and _attr(c, "symbol")
        and price and abs((_num(_attr(c, "strike_price"), price) / price) - 1) <= 0.12
    ][:80]
    quotes = get_latest_quotes(symbols)
    snapshots = get_option_snapshots(symbols)
    call_rows = _candidate_rows(calls, price, expiry, quotes, snapshots)
    put_rows = _candidate_rows(puts, price, expiry, quotes, snapshots)

    liquid = [r for r in call_rows + put_rows if r.get("quote_ok") and r.get("open_interest", 0) >= settings.MIN_OPEN_INTEREST]
    return {
        "available": True,
        "underlying": underlying,
        "underlying_price": price,
        "selected_expiration": expiry,
        "dte": _dte(expiry),
        "configured_dte_range": [settings.MIN_DTE, settings.MAX_DTE],
        "liquid_contracts": len(liquid),
        "calls": call_rows,
        "puts": put_rows,
        "chain_quality": {
            "quote_coverage": round(sum(1 for r in call_rows + put_rows if r.get("mid") is not None) / max(1, len(call_rows + put_rows)), 3),
            "liquid_quote_count": len(liquid),
        },
        "note": "Live quote, IV and Greeks are passed through when supplied by Alpaca; absent values are never fabricated.",
    }
