"""
Micro-bar engine: build sub-minute OHLCV bars from Alpaca trade data.

Alpaca's free/paper data plan only supports 1-minute bars as the smallest
bar timeframe. However, tick/trade data IS available (15-minute delayed).

This module fetches trade data and builds 15s/30s bars, which produce
5x more FVGs and 3.7x more liquidity sweeps than 1m bars — dramatically
improving ICT pattern detection density.

The 15-minute delay is handled gracefully: we use 1m bars for real-time
triggers and micro-bars for pattern enrichment (FVGs, sweeps, displacement
that occurred in the recent past).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
import pandas as pd
import numpy as np
from loguru import logger
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockTradesRequest
from config import settings


# Delay enforced by Alpaca free plan (seconds)
SIP_DELAY_SECONDS = 15 * 60

# Default micro-bar timeframe
DEFAULT_MICRO_SECONDS = 15

# Max trades per API call
TRADES_PAGE_SIZE = 10_000


def _make_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(
        settings.ALPACA_API_KEY,
        settings.ALPACA_SECRET_KEY,
    )


def fetch_trades(
    symbol: str,
    start: datetime,
    end: datetime,
    client: Optional[StockHistoricalDataClient] = None,
) -> pd.DataFrame:
    """
    Fetch trade/tick data for a symbol between start and end (UTC).
    Returns a DataFrame with columns: timestamp(index), price, size.
    Handles pagination internally.
    """
    if client is None:
        client = _make_client()

    all_dfs = []
    # Alpaca limits 10k trades per call. We chunk by 15-min windows
    # to stay under the limit for liquid symbols.
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(minutes=15), end)
        try:
            req = StockTradesRequest(
                symbol_or_symbols=symbol,
                limit=TRADES_PAGE_SIZE,
                start=chunk_start,
                end=chunk_end,
            )
            trades = client.get_stock_trades(req)
            df = trades.df if hasattr(trades, "df") else trades
            if hasattr(df, "reset_index"):
                df = df.reset_index()
            if len(df) > 0:
                all_dfs.append(df)
        except Exception as e:
            # 403 = SIP delay violation for recent data; silently skip
            if "403" in str(e) or "subscription" in str(e):
                logger.debug(f"Trades {chunk_start}–{chunk_end}: SIP delay, skipping")
            else:
                logger.warning(f"Trades {chunk_start}–{chunk_end}: {e}")
        chunk_start = chunk_end

    if not all_dfs:
        return pd.DataFrame(columns=["price", "size"])

    df = pd.concat(all_dfs, ignore_index=True)
    # Keep only needed columns
    cols = ["timestamp", "price", "size"]
    df = df[[c for c in cols if c in df.columns]]
    df = df.set_index("timestamp")
    return df


def build_micro_bars(
    symbol: str,
    seconds: int = 15,
    lookback_minutes: int = 120,
    client: Optional[StockHistoricalDataClient] = None,
) -> Optional[pd.DataFrame]:
    """
    Build sub-minute OHLCV bars from trade data.

    Args:
        symbol: Stock symbol (e.g. "SPY")
        seconds: Bar size in seconds (15 or 30)
        lookback_minutes: How far back to fetch trades
        client: Optional pre-built client

    Returns:
        DataFrame with open/high/low/close/volume columns, tz-aware UTC index.
        None if no trade data available.
    """
    now = datetime.now(timezone.utc)
    # Account for SIP delay — don't try to fetch data newer than the delay
    end = now - timedelta(seconds=SIP_DELAY_SECONDS)
    start = end - timedelta(minutes=lookback_minutes)

    trades = fetch_trades(symbol, start, end, client)
    if len(trades) < 10:
        logger.debug(f"{symbol}: only {len(trades)} trades for micro-bars")
        return None

    # Resample trades into OHLCV bars
    ohlcv = trades["price"].resample(f"{seconds}s").ohlc()
    ohlcv["volume"] = trades["size"].resample(f"{seconds}s").sum()
    ohlcv = ohlcv.dropna()

    if len(ohlcv) < 3:
        logger.debug(f"{symbol}: only {len(ohlcv)} micro-bars after resample")
        return None

    logger.debug(
        f"{symbol}: {len(ohlcv)} {seconds}s bars from {len(trades)} trades "
        f"({ohlcv.index[0]} to {ohlcv.index[-1]})"
    )
    return ohlcv


def build_micro_bars_multi(
    symbol: str,
    client: Optional[StockHistoricalDataClient] = None,
    lookback_minutes: int = 120,
) -> dict:
    """
    Build multiple micro-bar timeframes for enrichment.

    Returns dict with keys '15s', '30s' -> DataFrame or None.
    """
    trades_end = datetime.now(timezone.utc) - timedelta(seconds=SIP_DELAY_SECONDS)
    trades_start = trades_end - timedelta(minutes=lookback_minutes)

    trades = fetch_trades(symbol, trades_start, trades_end, client)
    if len(trades) < 10:
        return {"15s": None, "30s": None}

    result = {}
    for secs in [15, 30]:
        ohlcv = trades["price"].resample(f"{secs}s").ohlc()
        ohlcv["volume"] = trades["size"].resample(f"{secs}s").sum()
        ohlcv = ohlcv.dropna()
        result[f"{secs}s"] = ohlcv if len(ohlcv) >= 3 else None

    return result


def detect_micro_fvgs(df_micro: pd.DataFrame, max_count: int = 10) -> list:
    """
    Detect FVGs in micro-bar data. Returns list of FVG dicts.
    Much higher density than 1m FVGs.
    """
    if df_micro is None or len(df_micro) < 3:
        return []

    fvgs = []
    window = df_micro.iloc[-200:] if len(df_micro) > 200 else df_micro

    for i in range(2, len(window)):
        c_prev2 = window.iloc[i - 2]
        c_curr = window.iloc[i]

        # Bullish FVG
        if float(c_prev2["high"]) < float(c_curr["low"]):
            fvgs.append({
                "type": "bull",
                "top": float(c_curr["low"]),
                "bot": float(c_prev2["high"]),
                "ce": (float(c_curr["low"]) + float(c_prev2["high"])) / 2,
                "bar_offset": len(window) - i,
                "timeframe": "micro",
            })

        # Bearish FVG
        if float(c_prev2["low"]) > float(c_curr["high"]):
            fvgs.append({
                "type": "bear",
                "top": float(c_prev2["low"]),
                "bot": float(c_curr["high"]),
                "ce": (float(c_prev2["low"]) + float(c_curr["high"])) / 2,
                "bar_offset": len(window) - i,
                "timeframe": "micro",
            })

        if len(fvgs) >= max_count:
            break

    return fvgs


def detect_micro_sweeps(df_micro: pd.DataFrame, lookback: int = 10) -> list:
    """
    Detect liquidity sweeps in micro-bar data.
    Returns list of sweep events, most recent first.
    """
    if df_micro is None or len(df_micro) < lookback + 2:
        return []

    sweeps = []
    window = df_micro.iloc[-(lookback + 5):] if len(df_micro) > lookback + 5 else df_micro

    for i in range(3, len(window)):
        # Recent swing high/low (3-bar window before i)
        swing_high = float(window.iloc[i-3:i]["high"].max())
        swing_low = float(window.iloc[i-3:i]["low"].min())
        curr = window.iloc[i]

        # BSL sweep: takes out swing high, closes below
        if float(curr["high"]) > swing_high and float(curr["close"]) < swing_high:
            sweeps.append({
                "side": "bear",
                "level": swing_high,
                "type": "bsl_sweep",
                "timeframe": "micro",
                "bar_offset": len(window) - i - 1,
            })

        # SSL sweep: takes out swing low, closes above
        if float(curr["low"]) < swing_low and float(curr["close"]) > swing_low:
            sweeps.append({
                "side": "bull",
                "level": swing_low,
                "type": "ssl_sweep",
                "timeframe": "micro",
                "bar_offset": len(window) - i - 1,
            })

    return sweeps[-5:]  # last 5


def detect_micro_displacement(df_micro: pd.DataFrame, lookback: int = 8) -> Optional[dict]:
    """
    Detect displacement in micro-bar data.
    More sensitive than 5m displacement — catches intraday momentum bursts.
    """
    if df_micro is None or len(df_micro) < lookback + 2:
        return None

    recent = df_micro.iloc[-lookback:]
    avg_range = float(
        (df_micro["high"] - df_micro["low"]).iloc[:-lookback].mean()
    )
    if avg_range <= 0:
        return None

    move = float(recent["close"].iloc[-1] - recent["open"].iloc[0])
    total_range = float(recent["high"].max() - recent["low"].min())
    expansion_ratio = total_range / avg_range if avg_range > 0 else 0

    # Lower threshold for micro-bars (1.2x instead of 1.3x)
    if expansion_ratio < 1.2:
        return None

    direction = "bull" if move > 0 else "bear"
    return {
        "direction": direction,
        "move": round(move, 4),
        "range": round(total_range, 4),
        "expansion_ratio": round(expansion_ratio, 2),
        "bars": lookback,
        "timeframe": "micro",
    }


def enrich_rth_state(
    rth_state: dict,
    df_micro_15s: Optional[pd.DataFrame] = None,
    df_micro_30s: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Enrich an RTH market state with micro-bar pattern data.

    Adds:
    - micro_fvgs: FVGs from 15s bars (much higher density)
    - micro_sweeps: Liquidity sweeps from 15s bars
    - micro_displacement: Displacement from 15s bars
    - micro_fvg_count: Total FVG count
    - micro_sweep_count: Total sweep count
    - micro_evidence_score: 0.0-0.15 bonus to combined_score
    """
    micro_fvgs = []
    micro_sweeps = []
    micro_disp = None

    # Use 15s bars as primary micro source, 30s as fallback
    df_primary = df_micro_15s if df_micro_15s is not None else df_micro_30s

    if df_primary is not None:
        micro_fvgs = detect_micro_fvgs(df_primary, max_count=8)
        micro_sweeps = detect_micro_sweeps(df_primary, lookback=12)
        micro_disp = detect_micro_displacement(df_primary, lookback=8)

    # Add to state
    rth_state["micro_fvgs"] = micro_fvgs
    rth_state["micro_sweeps"] = micro_sweeps
    rth_state["micro_displacement"] = micro_disp
    rth_state["micro_fvg_count"] = len(micro_fvgs)
    rth_state["micro_sweep_count"] = len(micro_sweeps)

    # Compute micro evidence bonus (up to 0.15 extra on combined_score)
    micro_bonus = 0.0
    if micro_fvgs:
        micro_bonus += min(0.05, len(micro_fvgs) * 0.008)
    if micro_sweeps:
        micro_bonus += min(0.05, len(micro_sweeps) * 0.015)
    if micro_disp:
        micro_bonus += 0.05

    micro_bonus = round(min(0.15, micro_bonus), 3)
    rth_state["micro_evidence_bonus"] = micro_bonus

    # Boost combined score
    old_score = rth_state.get("combined_score", 0.0)
    new_score = round(min(1.0, old_score + micro_bonus), 2)
    rth_state["combined_score"] = new_score

    # Update score breakdown
    if "score_breakdown" not in rth_state:
        rth_state["score_breakdown"] = {}
    rth_state["score_breakdown"]["micro_evidence"] = micro_bonus

    # Update reason string
    reason = rth_state.get("reason", "")
    if micro_fvgs or micro_sweeps or micro_disp:
        parts = []
        if micro_fvgs:
            parts.append(f"microFVGx{len(micro_fvgs)}")
        if micro_sweeps:
            parts.append(f"microSweepx{len(micro_sweeps)}")
        if micro_disp:
            parts.append(f"microDisp_{micro_disp['direction']}")
        rth_state["reason"] = f"{reason} + " + " + ".join(parts) + f" + microBonus={micro_bonus:.3f}"

    # If micro displacement confirms or flips bias, note it
    if micro_disp:
        rth_state["micro_bias"] = micro_disp["direction"]
        # If micro bias agrees with RTH bias, boost confidence
        if rth_state.get("bias") == micro_disp["direction"]:
            rth_state["micro_bias_confirmed"] = True
        else:
            rth_state["micro_bias_confirmed"] = False

    return rth_state