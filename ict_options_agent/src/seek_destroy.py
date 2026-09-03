"""
ICT Seek & Destroy Profile detector
From "NQ Trading Seek & Destroy Profile Jackson Hole Symposium Day 1"
and classic ICT Seek & Destroy teachings.

When active: both sides of a prior range have been swept → choppy, low-edge environment.
Agent response: soft score penalty + warning flag (does NOT hard-block).
"""
from __future__ import annotations
from typing import Optional, Dict, Any
import pandas as pd
from loguru import logger


def _range_high_low(df: pd.DataFrame) -> tuple:
    if df.empty:
        return None, None
    return float(df["high"].max()), float(df["low"].min())


def detect_seek_and_destroy(df_15: pd.DataFrame, lookback: int = 60) -> Optional[Dict[str, Any]]:
    """
    Approximate Seek & Destroy:
    - Take a prior range (first ~1/3 of lookback = "Asia-like")
    - Check if a later window ("London / NY") has taken BOTH the high and the low of that range.
    - Also flag if recent price has swept both sides of the dealing-range style box.
    """
    if len(df_15) < lookback // 2:
        return None

    window = df_15.iloc[-lookback:]
    n = len(window)
    if n < 20:
        return None

    # Prior range ≈ first 40% of the window
    split = max(8, n // 3)
    prior = window.iloc[:split]
    later = window.iloc[split:]

    p_hi, p_lo = _range_high_low(prior)
    if p_hi is None or p_lo is None or p_hi <= p_lo:
        return None

    later_hi = float(later["high"].max())
    later_lo = float(later["low"].min())

    took_high = later_hi > p_hi
    took_low = later_lo < p_lo

    if took_high and took_low:
        # Classic Seek & Destroy signature
        return {
            "active": True,
            "type": "seek_destroy_both_sides",
            "prior_high": p_hi,
            "prior_low": p_lo,
            "later_high": later_hi,
            "later_low": later_lo,
            "severity": "high",
            "note": "Both sides of prior range swept – expect chop / low edge",
        }

    # Softer version: recent price has revisited both extremes of the whole window
    full_hi, full_lo = _range_high_low(window)
    recent = window.iloc[-12:]
    if (float(recent["high"].max()) >= full_hi * 0.999 and
        float(recent["low"].min()) <= full_lo * 1.001 and
        (full_hi - full_lo) / max(full_lo, 1) > 0.003):
        return {
            "active": True,
            "type": "seek_destroy_revisit",
            "prior_high": full_hi,
            "prior_low": full_lo,
            "severity": "medium",
            "note": "Price revisiting both extremes of recent range",
        }

    return {
        "active": False,
        "type": "clean",
        "severity": "none",
    }


def enrich_with_seek_destroy(
    signal: Dict[str, Any],
    df_15: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Additive: attach Seek & Destroy context.
    If active → reduce combined_score (soft penalty) and add warning.
    """
    if not signal:
        return signal
    out = dict(signal)

    snd = detect_seek_and_destroy(df_15)
    if not snd:
        return out

    out["seek_destroy"] = snd

    if snd.get("active"):
        penalty = 0.15 if snd.get("severity") == "high" else 0.08
        out["combined_score"] = max(0.2, out.get("combined_score", 0.7) - penalty)
        out["snd_warning"] = True
        # optional: force smaller size later in risk module if desired
    else:
        out["snd_warning"] = False

    return out
