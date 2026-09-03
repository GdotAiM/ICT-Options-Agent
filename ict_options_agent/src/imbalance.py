"""
ICT Imbalance / Efficiency / Order Block helpers
From "Monday Review On NQ & PreMarket Session Rules Revisited".

- Grade imbalances by candle BODIES (preferred over pure wicks)
- Buy-side / Sell-side efficiency (BISI / SIBI style)
- Order Blocks (last opposing candle before displacement)
- Key wick midpoint as confirmation level

Works TOGETHER with dealing-range, FVG, sweeps, time windows.
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List
import pandas as pd
import numpy as np
from loguru import logger


def body_high_low(row) -> tuple:
    """Return (body_high, body_low) of a candle."""
    o, c = float(row["open"]), float(row["close"])
    return max(o, c), min(o, c)


def detect_body_imbalances(df: pd.DataFrame, lookback: int = 40) -> List[Dict]:
    """
    Body-based imbalances (preferred grading method from the video).
    A bullish body imbalance: body_low of candle i > body_high of candle i-2
    (no body overlap across the middle candle).
    """
    imbalances = []
    if len(df) < 5:
        return imbalances

    for i in range(2, min(len(df), lookback + 2)):
        idx = -i
        c0 = df.iloc[idx]          # current / third
        c1 = df.iloc[idx - 1]      # middle
        c2 = df.iloc[idx - 2]      # first

        bh0, bl0 = body_high_low(c0)
        bh2, bl2 = body_high_low(c2)

        # Bullish body imbalance (buy-side efficiency potential)
        if bl0 > bh2:
            imbalances.append({
                "type": "bull_body_imb",
                "top": bl0,
                "bot": bh2,
                "mid": (bl0 + bh2) / 2,
                "bar_index": len(df) + idx,
                "strength": bl0 - bh2,
            })

        # Bearish body imbalance (sell-side efficiency potential)
        if bh0 < bl2:
            imbalances.append({
                "type": "bear_body_imb",
                "top": bl2,
                "bot": bh0,
                "mid": (bl2 + bh0) / 2,
                "bar_index": len(df) + idx,
                "strength": bl2 - bh0,
            })

    return imbalances


def detect_order_block(df: pd.DataFrame, bias: str, lookback: int = 20) -> Optional[Dict]:
    """
    Last opposing-direction candle before a displacement move.
    Bullish OB = last down-close candle before strong up move that breaks structure.
    Bearish OB = last up-close candle before strong down move.
    """
    if len(df) < lookback + 3:
        return None

    recent = df.iloc[-lookback:]
    for i in range(len(recent) - 3, 2, -1):
        candle = recent.iloc[i]
        o, c = float(candle["open"]), float(candle["close"])
        is_down = c < o
        is_up = c > o

        # Look for displacement after this candle
        after = recent.iloc[i + 1 : i + 4]
        if after.empty:
            continue

        if bias == "bull" and is_down:
            # strong up displacement after
            if float(after["close"].iloc[-1]) > float(candle["high"]) * 1.001:
                return {
                    "type": "bull_ob",
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "mid": (float(candle["high"]) + float(candle["low"])) / 2,
                    "open": o,
                    "close": c,
                }
        if bias == "bear" and is_up:
            if float(after["close"].iloc[-1]) < float(candle["low"]) * 0.999:
                return {
                    "type": "bear_ob",
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "mid": (float(candle["high"]) + float(candle["low"])) / 2,
                    "open": o,
                    "close": c,
                }
    return None


def key_wick_midpoint(df: pd.DataFrame, side: str = "high") -> Optional[float]:
    """
    Midpoint of the most significant recent wick (video uses close below/above
    midpoint of a key wick as confirmation).
    """
    if len(df) < 5:
        return None
    recent = df.iloc[-15:]
    if side == "high":
        # largest upper wick
        upper = recent["high"] - recent[["open", "close"]].max(axis=1)
        idx = upper.idxmax()
        row = recent.loc[idx]
        body_top = max(float(row["open"]), float(row["close"]))
        return (float(row["high"]) + body_top) / 2
    else:
        lower = recent[["open", "close"]].min(axis=1) - recent["low"]
        idx = lower.idxmax()
        row = recent.loc[idx]
        body_bot = min(float(row["open"]), float(row["close"]))
        return (float(row["low"]) + body_bot) / 2


def enrich_with_imbalance_and_ob(
    signal: Dict[str, Any],
    df_15: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Additive enrichment – never overrides core signal.
    Adds body imbalances, order block, wick midpoint.
    """
    if not signal:
        return signal

    out = dict(signal)
    bias = signal.get("bias", "bull")

    # Body-graded imbalances
    imbs = detect_body_imbalances(df_15)
    relevant = [x for x in imbs if (bias == "bull" and "bull" in x["type"]) or (bias == "bear" and "bear" in x["type"])]
    if relevant:
        # strongest (largest) recent
        best = max(relevant, key=lambda x: x["strength"])
        out["body_imbalance"] = best
        out["imb_mid"] = best["mid"]
        # soft score boost if price is near the imbalance mid
        price = signal.get("underlying_price", 0)
        if price and abs(price - best["mid"]) / price < 0.004:
            out["combined_score"] = min(1.0, signal.get("combined_score", 0.7) + 0.06)

    # Order Block
    ob = detect_order_block(df_15, bias)
    if ob:
        out["order_block"] = ob
        out["ob_mid"] = ob["mid"]
        # if entry is near OB mid, boost
        entry = signal.get("entry_zone", 0)
        if entry and abs(entry - ob["mid"]) / max(entry, 1) < 0.003:
            out["combined_score"] = min(1.0, out.get("combined_score", 0.7) + 0.05)

    # Key wick midpoint (confirmation level)
    wick_side = "low" if bias == "bull" else "high"
    wick_mid = key_wick_midpoint(df_15, wick_side)
    if wick_mid:
        out["key_wick_mid"] = wick_mid

    return out
