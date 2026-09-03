"""
Live option quote helpers using Alpaca Option Data API.

Includes quality gates: reject a quote as unusable if it's stale (broker
timestamp too old) or too wide (bid-ask spread is a large fraction of mid).
A bad quote must never silently become a fabricated price — every function
here returns an explicit ok/reason instead of guessing.
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionLatestQuoteRequest, OptionSnapshotRequest
from loguru import logger
from config import settings


def get_option_data_client() -> OptionHistoricalDataClient:
    return OptionHistoricalDataClient(
        settings.ALPACA_API_KEY,
        settings.ALPACA_SECRET_KEY,
    )


def get_latest_quotes(symbols: List[str]) -> Dict[str, Any]:
    """Return latest quotes keyed by option symbol."""
    if not symbols:
        return {}
    client = get_option_data_client()
    try:
        req = OptionLatestQuoteRequest(symbol_or_symbols=symbols)
        quotes = client.get_option_latest_quote(req)
        return quotes
    except Exception as e:
        logger.error(f"Latest quote fetch failed: {e}")
        return {}


def get_option_snapshots(symbols: List[str]) -> Dict[str, Any]:
    """Return broker option snapshots (IV/Greeks when available)."""
    if not symbols:
        return {}
    client = get_option_data_client()
    try:
        req = OptionSnapshotRequest(symbol_or_symbols=symbols)
        return client.get_option_snapshot(req)
    except Exception as e:
        logger.warning(f"Option snapshot fetch failed: {e}")
        return {}


def _field(quote, obj_attr: str, dict_key: str):
    """Read a field from either a real Alpaca model (attribute) or a
    dict/fake quote used in tests (key)."""
    val = getattr(quote, obj_attr, None)
    if val is None and hasattr(quote, "get"):
        val = quote.get(dict_key)
    return val


def quote_age_seconds(quote) -> Optional[float]:
    """Seconds since the quote's own timestamp. None if no timestamp present
    (never treated as stale by omission — caller decides what missing means)."""
    ts = _field(quote, "timestamp", "t")
    if ts is None:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        # Naive timestamps are treated as UTC ( Alpaca sends UTC strings;
        # local-naive timestamps from tests should also compare against UTC now).
        # Use a timezone-aware reference point so the subtraction is always
        # correct regardless of the machine's local UTC offset.
        ts = ts.replace(tzinfo=timezone.utc)
    now_utc = datetime.now(timezone.utc)
    return (now_utc - ts).total_seconds()


def evaluate_quote(
    quote,
    max_spread_pct: float = None,
    max_age_seconds: float = None,
) -> Tuple[bool, Optional[float], str]:
    """
    Single source of truth for "is this quote usable". Returns (ok, mid, reason).
    ok=False means: do not trade on this price, at all — the caller must skip
    the leg/trade rather than substitute a guessed number.
    """
    max_spread_pct = settings.MAX_QUOTE_SPREAD_PCT if max_spread_pct is None else max_spread_pct
    max_age_seconds = settings.MAX_QUOTE_AGE_SECONDS if max_age_seconds is None else max_age_seconds

    raw_bid = _field(quote, "bid_price", "bp")
    raw_ask = _field(quote, "ask_price", "ap")
    try:
        bid = float(raw_bid) if raw_bid is not None else 0.0
        ask = float(raw_ask) if raw_ask is not None else 0.0
    except (TypeError, ValueError):
        return False, None, "unparseable bid/ask on quote"

    if bid <= 0 and ask <= 0:
        return False, None, "no bid or ask (empty/dead quote)"

    if bid > 0 and ask > 0:
        if ask < bid:
            return False, None, f"crossed quote (bid ${bid:.2f} > ask ${ask:.2f})"
        mid = (bid + ask) / 2.0
        spread = ask - bid
        spread_pct = (spread / mid) if mid > 0 else 1.0
        if spread_pct > max_spread_pct:
            return False, mid, (
                f"spread ${spread:.2f} is {spread_pct:.1%} of mid ${mid:.2f} "
                f"(max {max_spread_pct:.0%}) — quote too wide to trade"
            )
    elif ask > 0:
        mid = ask
    else:
        mid = bid

    age = quote_age_seconds(quote)
    if age is not None and age > max_age_seconds:
        return False, mid, f"quote is {age:.0f}s old (max {max_age_seconds:.0f}s) — stale"

    return True, mid, ""


def mid_price(quote) -> Optional[float]:
    """Best mid from a quote object, with no quality gate applied. Kept for
    backward compatibility / ad-hoc inspection — trade-path code should use
    evaluate_quote() instead so a bad quote can't silently pass through."""
    ok, mid, _ = evaluate_quote(quote, max_spread_pct=float("inf"), max_age_seconds=float("inf"))
    return mid


def net_debit_credit(
    long_symbol: str, short_symbol: str
) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
    """
    Returns (net_debit_or_credit, long_mid, short_mid, reason).
    Positive net = debit paid, negative = credit received.
    net is None whenever either leg's quote fails the quality gate (missing,
    crossed, too wide, or stale) — reason explains why. Callers must treat
    None as "skip this trade", never substitute a guessed price.
    """
    quotes = get_latest_quotes([long_symbol, short_symbol])
    if long_symbol not in quotes or short_symbol not in quotes:
        return None, None, None, "one or both legs missing from quote response"

    long_ok, long_mid, long_reason = evaluate_quote(quotes[long_symbol])
    if not long_ok:
        return None, long_mid, None, f"long leg {long_symbol}: {long_reason}"

    short_ok, short_mid, short_reason = evaluate_quote(quotes[short_symbol])
    if not short_ok:
        return None, long_mid, short_mid, f"short leg {short_symbol}: {short_reason}"

    net = long_mid - short_mid  # positive = debit
    return net, long_mid, short_mid, ""


def iron_condor_credit(
    long_put: str, short_put: str, short_call: str, long_call: str
) -> Tuple[Optional[float], Dict[str, float], str]:
    """
    Net credit for a classic iron condor (sell put spread + sell call spread).
    Returns (credit, mids_dict, reason). credit is None if any leg fails the
    quality gate — callers must skip the trade, not substitute a guess.
    """
    symbols = [long_put, short_put, short_call, long_call]
    quotes = get_latest_quotes(symbols)
    mids = {}
    for s in symbols:
        if s not in quotes:
            return None, {}, f"{s}: missing from quote response"
        ok, mid, reason = evaluate_quote(quotes[s])
        if not ok:
            return None, {}, f"{s}: {reason}"
        mids[s] = mid

    # Credit = (short_put mid - long_put mid) + (short_call mid - long_call mid)
    put_credit = mids[short_put] - mids[long_put]
    call_credit = mids[short_call] - mids[long_call]
    total_credit = put_credit + call_credit
    return max(0.0, total_credit), mids, ""
