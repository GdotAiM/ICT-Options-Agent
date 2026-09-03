"""
ICT Pre-market Dealing Range + Octants + Consequent Encroachment
From "NQ Consolidation Day Algorithmic Rules In Action".

Works TOGETHER with existing sweep / MSS / FVG / PD / kill-zone logic.
"""
from __future__ import annotations
from datetime import datetime, time, timedelta
from typing import Optional, Dict, Any, List, Tuple
import pandas as pd
import numpy as np
from loguru import logger
import pytz


ET = pytz.timezone("US/Eastern")


def _filter_premarket(df: pd.DataFrame, date: Optional[datetime] = None) -> pd.DataFrame:
    """
    Return bars that fall inside 07:00–09:00 ET on the given (or latest) day.
    Expects df index to be timezone-aware or naive (assumed ET).
    """
    if df.empty:
        return df

    idx = df.index
    if idx.tz is None:
        # assume ET
        idx = idx.tz_localize(ET, ambiguous="infer", nonexistent="shift_forward")
        df = df.copy()
        df.index = idx

    if date is None:
        # use the most recent date present in the data
        date = df.index[-1].astimezone(ET).date()

    start = ET.localize(datetime.combine(date, time(7, 0)))
    end = ET.localize(datetime.combine(date, time(9, 0)))

    mask = (df.index >= start) & (df.index < end)
    return df.loc[mask]


def compute_dealing_range(df_15: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """
    Pre-market 7–9 ET high/low = dealing range for the day.
    Returns equilibrium, octants, premium/discount boundaries.
    """
    prem = _filter_premarket(df_15)
    if prem.empty or len(prem) < 2:
        # fallback: use first 90 minutes of available data or last 20 bars
        prem = df_15.iloc[: max(6, len(df_15) // 8)]
        if prem.empty:
            return None

    hi = float(prem["high"].max())
    lo = float(prem["low"].min())
    if hi <= lo:
        return None

    rng = hi - lo
    eq = (hi + lo) / 2.0  # equilibrium

    # 8 octants (0 = low, 8 = high)
    octants = [lo + (rng * i / 8.0) for i in range(9)]

    return {
        "high": hi,
        "low": lo,
        "range": rng,
        "equilibrium": eq,
        "octants": octants,          # index 0=low … 8=high
        "premium_start": eq,         # above eq = premium
        "discount_end": eq,          # below eq = discount
        "upper_octant": octants[6],  # ~75%
        "lower_octant": octants[2],  # ~25%
        "source": "premarket_7_9" if len(_filter_premarket(df_15)) >= 2 else "fallback",
    }


def consequent_encroachment(fvg_top: float, fvg_bot: float, bias: str) -> float:
    """
    Consequent Encroachment (CE) of an FVG / inefficiency.
    Classic ICT: 50% of the gap (sometimes refined to body).
    For bullish FVG we often look for price to trade to the CE from above;
    for bearish from below.
    """
    return (fvg_top + fvg_bot) / 2.0


def inversion_fvg_simple(df: pd.DataFrame) -> Optional[Dict]:
    """
    Very lightweight inversion FVG detector.
    A previous FVG that price has traded through and is now acting in the opposite role.
    Returns the most recent candidate if any.
    """
    df = df.copy()
    # Re-use basic 3-candle gap logic
    bull = (df["high"].shift(2) < df["low"])
    bear = (df["low"].shift(2) > df["high"])

    # Look for a prior bull FVG that has been fully traded through (price closed below its bot)
    # and is now being respected from the other side – simplified signal only
    for i in range(len(df) - 4, max(5, len(df) - 30), -1):
        if bull.iloc[i]:
            top = float(df["low"].iloc[i])
            bot = float(df["high"].iloc[i - 2])
            # has price closed through it later?
            later = df.iloc[i + 1 :]
            if (later["close"] < bot).any():
                return {
                    "type": "inversion_bull_to_bear",
                    "top": top,
                    "bot": bot,
                    "ce": consequent_encroachment(top, bot, "bear"),
                }
        if bear.iloc[i]:
            top = float(df["low"].iloc[i - 2])
            bot = float(df["high"].iloc[i])
            later = df.iloc[i + 1 :]
            if (later["close"] > top).any():
                return {
                    "type": "inversion_bear_to_bull",
                    "top": top,
                    "bot": bot,
                    "ce": consequent_encroachment(top, bot, "bull"),
                }
    return None


def refine_entry_with_ce_and_octants(
    signal: Dict[str, Any],
    dealing: Optional[Dict[str, Any]],
    df_15: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Enrich an existing ICT signal with dealing-range context,
    preferred CE entry, and octant alignment.
    Does NOT override the original signal – only adds confluence.
    """
    if not signal:
        return signal

    enriched = dict(signal)

    if dealing:
        enriched["dealing_range"] = {
            "high": dealing["high"],
            "low": dealing["low"],
            "equilibrium": dealing["equilibrium"],
            "source": dealing["source"],
        }
        price = signal["underlying_price"]
        # where is current price relative to pre-market range?
        if price >= dealing["equilibrium"]:
            enriched["dr_zone"] = "premium"
        else:
            enriched["dr_zone"] = "discount"

        # octant position (0–8)
        if dealing["range"] > 0:
            pos = (price - dealing["low"]) / dealing["range"]
            enriched["octant"] = round(pos * 8, 1)

        # Prefer entry nearer to CE of the FVG we already found
        # or to the nearest relevant octant
        entry = signal.get("entry_zone", price)
        if "bull_fvg" in str(signal.get("reason", "")).lower() or signal["bias"] == "bull":
            # bias long → prefer lower octant / CE in discount
            target_level = dealing["lower_octant"]
        else:
            target_level = dealing["upper_octant"]

        # blend original entry with CE/octant (soft)
        enriched["entry_zone_refined"] = (entry * 0.6) + (target_level * 0.4)
        enriched["preferred_octant_level"] = target_level

    # Inversion FVG as extra confluence
    inv = inversion_fvg_simple(df_15)
    if inv:
        enriched["inversion_fvg"] = inv
        enriched["ce"] = inv["ce"]
        # if CE is close to our entry, boost confidence
        if abs(inv["ce"] - signal.get("entry_zone", 0)) / max(signal.get("underlying_price", 1), 1) < 0.003:
            enriched["combined_score"] = min(1.0, signal.get("combined_score", 0.7) + 0.08)

    return enriched
