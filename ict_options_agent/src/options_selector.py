"""
Options chain fetching and strike selection for debit spreads and iron condors.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from collections import Counter
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.trading.enums import ContractType, AssetStatus
from loguru import logger
from config.settings import (
    MIN_DTE,
    MAX_DTE,
    SPREAD_WIDTH_TARGET,
    MIN_OPEN_INTEREST,
    MIN_OPTION_VOLUME,
)


def _passes_liquidity(contract) -> bool:
    """Filter illiquid contracts by open interest and (optional) volume."""
    try:
        oi = getattr(contract, "open_interest", None)
        if oi is not None and MIN_OPEN_INTEREST > 0:
            if int(oi) < MIN_OPEN_INTEREST:
                return False
        vol = getattr(contract, "volume", None)
        if vol is not None and MIN_OPTION_VOLUME > 0:
            if int(vol) < MIN_OPTION_VOLUME:
                return False
    except (TypeError, ValueError):
        pass
    return True


def get_option_contracts(
    client: TradingClient,
    underlying: str,
    contract_type: ContractType,
    min_dte: int = MIN_DTE,
    max_dte: int = MAX_DTE,
) -> List:
    today = datetime.now().date()
    req = GetOptionContractsRequest(
        underlying_symbols=[underlying],
        status=AssetStatus.ACTIVE,
        expiration_date_gte=today + timedelta(days=min_dte),
        expiration_date_lte=today + timedelta(days=max_dte),
        type=contract_type,
        limit=300,
    )
    try:
        resp = client.get_option_contracts(req)
        contracts = resp.option_contracts or []
        filtered = [c for c in contracts if _passes_liquidity(c)]
        if len(filtered) < len(contracts):
            logger.debug(
                f"{underlying} {contract_type}: {len(contracts)} → {len(filtered)} "
                f"after OI>={MIN_OPEN_INTEREST} vol>={MIN_OPTION_VOLUME}"
            )
        return filtered
    except Exception as e:
        logger.error(f"Failed to fetch contracts for {underlying}: {e}")
        return []


def _nearest(contracts: List, target: float):
    return min(contracts, key=lambda c: abs(float(c.strike_price) - target))


def select_bull_call_spread(
    client: TradingClient,
    underlying: str,
    signal: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    contracts = get_option_contracts(client, underlying, ContractType.CALL)
    if not contracts:
        return None

    preferred_exp = signal.get("ai_selected_expiration")
    if preferred_exp:
        preferred = [c for c in contracts if str(c.expiration_date)[:10] == str(preferred_exp)[:10]]
        if preferred:
            contracts = preferred
    calls = sorted(
        [c for c in contracts if c.strike_price is not None],
        key=lambda x: float(x.strike_price),
    )
    if len(calls) < 2:
        return None

    price = signal["underlying_price"]
    entry = signal.get("entry_zone", price)

    long_c = _nearest(calls, entry)
    desired_short = float(long_c.strike_price) + SPREAD_WIDTH_TARGET
    short_candidates = [c for c in calls if float(c.strike_price) > float(long_c.strike_price)]
    if not short_candidates:
        return None
    short_c = _nearest(short_candidates, desired_short)

    return {
        "type": "bull_call_spread",
        "long": long_c,
        "short": short_c,
        "long_strike": float(long_c.strike_price),
        "short_strike": float(short_c.strike_price),
        "expiration": long_c.expiration_date,
        "legs": [
            {"symbol": long_c.symbol, "side": "buy", "role": "long_call"},
            {"symbol": short_c.symbol, "side": "sell", "role": "short_call"},
        ],
    }


def select_bear_put_spread(
    client: TradingClient,
    underlying: str,
    signal: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    contracts = get_option_contracts(client, underlying, ContractType.PUT)
    if not contracts:
        return None

    preferred_exp = signal.get("ai_selected_expiration")
    if preferred_exp:
        preferred = [c for c in contracts if str(c.expiration_date)[:10] == str(preferred_exp)[:10]]
        if preferred:
            contracts = preferred
    puts = sorted(
        [c for c in contracts if c.strike_price is not None],
        key=lambda x: float(x.strike_price),
    )
    if len(puts) < 2:
        return None

    price = signal["underlying_price"]
    entry = signal.get("entry_zone", price)

    long_p = _nearest(puts, entry)
    desired_short = float(long_p.strike_price) - SPREAD_WIDTH_TARGET
    short_candidates = [c for c in puts if float(c.strike_price) < float(long_p.strike_price)]
    if not short_candidates:
        return None
    short_p = _nearest(short_candidates, desired_short)

    return {
        "type": "bear_put_spread",
        "long": long_p,
        "short": short_p,
        "long_strike": float(long_p.strike_price),
        "short_strike": float(short_p.strike_price),
        "expiration": long_p.expiration_date,
        "legs": [
            {"symbol": long_p.symbol, "side": "buy", "role": "long_put"},
            {"symbol": short_p.symbol, "side": "sell", "role": "short_put"},
        ],
    }


def select_iron_condor(
    client: TradingClient,
    underlying: str,
    signal: Dict[str, Any],
    wing_width: float = None,
    body_width: float = None,
) -> Optional[Dict[str, Any]]:
    """
    Classic short iron condor: sell OTM put spread + sell OTM call spread.
    """
    wing_width = wing_width or SPREAD_WIDTH_TARGET
    body_width = body_width or (SPREAD_WIDTH_TARGET * 2)

    calls = get_option_contracts(client, underlying, ContractType.CALL)
    puts = get_option_contracts(client, underlying, ContractType.PUT)
    if not calls or not puts:
        return None

    preferred_exp = signal.get("ai_selected_expiration")
    if preferred_exp:
        pc = [c for c in calls if str(c.expiration_date)[:10] == str(preferred_exp)[:10]]
        pp = [p for p in puts if str(p.expiration_date)[:10] == str(preferred_exp)[:10]]
        if pc and pp:
            calls, puts = pc, pp
    calls = sorted([c for c in calls if c.strike_price], key=lambda x: float(x.strike_price))
    puts = sorted([c for c in puts if c.strike_price], key=lambda x: float(x.strike_price))

    all_exps = [c.expiration_date for c in calls + puts]
    if not all_exps:
        return None
    best_exp = Counter(all_exps).most_common(1)[0][0]
    calls = [c for c in calls if c.expiration_date == best_exp]
    puts = [c for c in puts if c.expiration_date == best_exp]
    if len(calls) < 2 or len(puts) < 2:
        return None

    price = signal["underlying_price"]

    short_put_target = price - body_width / 2
    long_put_target = short_put_target - wing_width
    short_call_target = price + body_width / 2
    long_call_target = short_call_target + wing_width

    short_put = _nearest(puts, short_put_target)
    long_cands = [p for p in puts if float(p.strike_price) < float(short_put.strike_price)]
    if not long_cands:
        return None
    long_put = _nearest(long_cands, long_put_target)

    short_call = _nearest(calls, short_call_target)
    long_cands_c = [c for c in calls if float(c.strike_price) > float(short_call.strike_price)]
    if not long_cands_c:
        return None
    long_call = _nearest(long_cands_c, long_call_target)

    return {
        "type": "iron_condor",
        "long_put": long_put,
        "short_put": short_put,
        "short_call": short_call,
        "long_call": long_call,
        "expiration": best_exp,
        "strikes": {
            "long_put": float(long_put.strike_price),
            "short_put": float(short_put.strike_price),
            "short_call": float(short_call.strike_price),
            "long_call": float(long_call.strike_price),
        },
        "legs": [
            {"symbol": long_put.symbol, "side": "buy", "role": "long_put"},
            {"symbol": short_put.symbol, "side": "sell", "role": "short_put"},
            {"symbol": short_call.symbol, "side": "sell", "role": "short_call"},
            {"symbol": long_call.symbol, "side": "buy", "role": "long_call"},
        ],
    }
