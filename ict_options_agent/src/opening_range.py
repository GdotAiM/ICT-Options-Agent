"""
Opening Range Gap (ORG), First-Presented FVG, Wick-as-Imbalance
From "NQ High Of Day Short Review".

Works TOGETHER with dealing-range, body imbalances, OBs, time windows, etc.
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List
from datetime import datetime, time, timedelta
import pandas as pd
import numpy as np
from loguru import logger
import pytz

ET = pytz.timezone("US/Eastern")


def opening_range_gap(df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """
    Opening Range Gap = previous regular-session close vs current session open.
    Returns mid-gap and simple octants. Video notes ~70% rule toward mid-gap by 10:00 ET.
    """
    if len(df) < 20:
        return None

    # Approximate: take last close of previous day vs first open of current day
    # For simplicity on continuous bars we use the largest overnight-style gap
    # in the most recent data.
    df = df.copy()
    if df.index.tz is None:
        try:
            df.index = df.index.tz_localize(ET, ambiguous="infer", nonexistent="shift_forward")
        except Exception:
            pass

    # Group by date
    try:
        dates = df.index.date
        unique_dates = sorted(set(dates))
        if len(unique_dates) < 2:
            # fallback: use first bar open vs prior close
            prev_close = float(df["close"].iloc[-15])
            curr_open = float(df["open"].iloc[-1])
        else:
            prev_day = unique_dates[-2]
            curr_day = unique_dates[-1]
            prev_bars = df[df.index.date == prev_day]
            curr_bars = df[df.index.date == curr_day]
            if prev_bars.empty or curr_bars.empty:
                return None
            prev_close = float(prev_bars["close"].iloc[-1])
            curr_open = float(curr_bars["open"].iloc[0])
    except Exception:
        prev_close = float(df["close"].iloc[-10])
        curr_open = float(df["open"].iloc[-1])

    gap = curr_open - prev_close
    mid = (curr_open + prev_close) / 2.0
    # simple 4 divisions (octants of the gap)
    levels = [prev_close + gap * i / 4 for i in range(5)] if gap != 0 else [prev_close] * 5

    return {
        "prev_close": prev_close,
        "curr_open": curr_open,
        "gap": gap,
        "mid_gap": mid,
        "gap_levels": levels,  # 0=prev_close … 4=curr_open
        "direction": "up" if gap > 0 else "down",
    }


def first_presented_fvg(df: pd.DataFrame, lookback: int = 80) -> Optional[Dict]:
    """
    First-Presented FVG of the recent window (approximation of FPFG).
    Returns the earliest (oldest) still-relevant 3-candle imbalance.
    """
    if len(df) < 10:
        return None

    window = df.iloc[-lookback:] if len(df) > lookback else df
    # scan from oldest to newest so first presented is found first
    for i in range(2, len(window)):
        c0 = window.iloc[i]
        c2 = window.iloc[i - 2]
        # bullish FVG
        if float(c2["high"]) < float(c0["low"]):
            return {
                "type": "fpfvg_bull",
                "top": float(c0["low"]),
                "bot": float(c2["high"]),
                "ce": (float(c0["low"]) + float(c2["high"])) / 2,
                "bar_offset": len(window) - i,
            }
        # bearish FVG
        if float(c2["low"]) > float(c0["high"]):
            return {
                "type": "fpfvg_bear",
                "top": float(c2["low"]),
                "bot": float(c0["high"]),
                "ce": (float(c2["low"]) + float(c0["high"])) / 2,
                "bar_offset": len(window) - i,
            }
    return None


def wick_as_imbalance(df: pd.DataFrame, side: str = "high") -> Optional[Dict]:
    """
    Treat a significant wick as an imbalance.
    Fib / CE from body extreme to wick extreme.
    """
    if len(df) < 5:
        return None
    recent = df.iloc[-12:]
    if side == "high":
        upper = recent["high"] - recent[["open", "close"]].max(axis=1)
        idx = upper.idxmax()
        row = recent.loc[idx]
        body_top = max(float(row["open"]), float(row["close"]))
        wick_high = float(row["high"])
        if wick_high <= body_top:
            return None
        return {
            "type": "wick_imb_high",
            "body": body_top,
            "extreme": wick_high,
            "ce": (body_top + wick_high) / 2,
            "range": wick_high - body_top,
        }
    else:
        lower = recent[["open", "close"]].min(axis=1) - recent["low"]
        idx = lower.idxmax()
        row = recent.loc[idx]
        body_bot = min(float(row["open"]), float(row["close"]))
        wick_low = float(row["low"])
        if wick_low >= body_bot:
            return None
        return {
            "type": "wick_imb_low",
            "body": body_bot,
            "extreme": wick_low,
            "ce": (body_bot + wick_low) / 2,
            "range": body_bot - wick_low,
        }


def grade_range(high: float, low: float) -> Dict[str, float]:
    """Grade any range into octants / quadrants / CE (used for daily inefficiencies + RTH ORG)."""
    if high <= low:
        return {}
    rng = high - low
    return {
        "high": high,
        "low": low,
        "ce": (high + low) / 2,
        "q1": low + rng * 0.25,
        "q3": low + rng * 0.75,
        "o1": low + rng * 0.125,
        "o3": low + rng * 0.375,
        "o5": low + rng * 0.625,
        "o7": low + rng * 0.875,
    }


def rth_opening_range_gap(df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """
    RTH-focused ORG (from Chain of Custody With RTH ORG lecture).
    Anchors to regular-session open vs prior close and grades the gap.
    """
    base = opening_range_gap(df)
    if not base:
        return None
    graded = grade_range(
        max(base["prev_close"], base["curr_open"]),
        min(base["prev_close"], base["curr_open"]),
    )
    base["graded"] = graded
    base["rth"] = True
    return base


def daily_inefficiency_proxy(df: pd.DataFrame, lookback: int = 80) -> Optional[Dict[str, Any]]:
    """
    Lightweight proxy for daily volume-imbalance / suspension-block style inefficiency.
    Takes a larger recent swing and grades it (Chain of Custody With Daily Inefficiencies).
    """
    if len(df) < lookback // 2:
        return None
    window = df.iloc[-lookback:]
    hi = float(window["high"].max())
    lo = float(window["low"].min())
    if hi <= lo:
        return None
    graded = grade_range(hi, lo)
    return {
        "type": "daily_inefficiency_proxy",
        "high": hi,
        "low": lo,
        "graded": graded,
        "ce": graded.get("ce"),
    }


def enrich_with_org_and_fpfvg(
    signal: Dict[str, Any],
    df_15: pd.DataFrame,
) -> Dict[str, Any]:
    """Additive enrichment from High-of-Day + RTH ORG + Daily Inefficiency lectures."""
    if not signal:
        return signal
    out = dict(signal)
    price = signal.get("underlying_price", 0)
    bias = signal.get("bias", "bull")

    # Classic ORG
    org = opening_range_gap(df_15)
    if org:
        out["opening_range_gap"] = org
        out["mid_gap"] = org["mid_gap"]
        if price and abs(price - org["mid_gap"]) / max(price, 1) < 0.004:
            out["combined_score"] = min(1.0, out.get("combined_score", 0.7) + 0.05)

    # RTH-graded ORG
    rth = rth_opening_range_gap(df_15)
    if rth and rth.get("graded"):
        out["rth_org"] = rth
        g = rth["graded"]
        # boost if price is near a graded level
        for key in ("ce", "q1", "q3", "o3", "o5"):
            lvl = g.get(key)
            if lvl and price and abs(price - lvl) / max(price, 1) < 0.0025:
                out["combined_score"] = min(1.0, out.get("combined_score", 0.7) + 0.04)
                break

    # Daily inefficiency proxy (graded)
    daily = daily_inefficiency_proxy(df_15)
    if daily:
        out["daily_inefficiency"] = daily
        if daily.get("ce") and price and abs(price - daily["ce"]) / max(price, 1) < 0.003:
            out["combined_score"] = min(1.0, out.get("combined_score", 0.7) + 0.05)

    # First Presented FVG
    fpfvg = first_presented_fvg(df_15)
    if fpfvg:
        out["fpfvg"] = fpfvg
        out["fpfvg_ce"] = fpfvg["ce"]
        if price and abs(price - fpfvg["ce"]) / max(price, 1) < 0.003:
            out["combined_score"] = min(1.0, out.get("combined_score", 0.7) + 0.07)

    # Wick as imbalance
    wick_side = "high" if bias == "bear" else "low"
    wick = wick_as_imbalance(df_15, wick_side)
    if wick:
        out["wick_imbalance"] = wick
        out["wick_ce"] = wick["ce"]
        if price and abs(price - wick["ce"]) / max(price, 1) < 0.0025:
            out["combined_score"] = min(1.0, out.get("combined_score", 0.7) + 0.05)

    return out

