"""
ICT-inspired confluence detectors — rule-based, fully testable approximations.

This is intentionally a **rule-based ICT-inspired confluence model**, not a
faithful reproduction of every Inner Circle Trader concept. Heuristics for
liquidity sweeps, market structure shifts, FVGs, order blocks, dealing range,
opening-range gaps, Seek & Destroy, and Chain of Custody are simplified so
they are deterministic, unit-testable, and suitable for a short hackathon
window. Scores are additive confluence weights, not probability estimates.
"""
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List
from config.settings import SWING_LOOKBACK, FVG_MIN_RELATIVE_SIZE
from loguru import logger


def detect_swings(df: pd.DataFrame, lookback: int = SWING_LOOKBACK) -> pd.DataFrame:
    df = df.copy()
    window = lookback * 2 + 1
    df["swing_high"] = df["high"].where(
        df["high"] == df["high"].rolling(window, center=True).max()
    )
    df["swing_low"] = df["low"].where(
        df["low"] == df["low"].rolling(window, center=True).min()
    )
    return df


def detect_fvg(df: pd.DataFrame) -> pd.DataFrame:
    """Three-candle Fair Value Gaps."""
    df = df.copy()
    # Bullish FVG: high[i-2] < low[i]
    bull_cond = df["high"].shift(2) < df["low"]
    df["bull_fvg_bot"] = np.where(bull_cond, df["high"].shift(2), np.nan)
    df["bull_fvg_top"] = np.where(bull_cond, df["low"], np.nan)

    # Bearish FVG
    bear_cond = df["low"].shift(2) > df["high"]
    df["bear_fvg_top"] = np.where(bear_cond, df["low"].shift(2), np.nan)
    df["bear_fvg_bot"] = np.where(bear_cond, df["high"], np.nan)
    return df


def premium_discount(df: pd.DataFrame, lookback: int = 50) -> Dict[str, Any]:
    recent = df.iloc[-lookback:]
    rh = recent["high"].max()
    rl = recent["low"].min()
    mid = (rh + rl) / 2
    last = df["close"].iloc[-1]
    zone = "discount" if last < mid else "premium"
    return {"zone": zone, "mid": mid, "range_high": rh, "range_low": rl}


def find_recent_swing_levels(df: pd.DataFrame, n: int = 5) -> Dict[str, List[float]]:
    highs = df["swing_high"].dropna().tail(n).tolist()
    lows = df["swing_low"].dropna().tail(n).tolist()
    return {"highs": highs, "lows": lows}


def detect_liquidity_sweep(df: pd.DataFrame, lookback: int = 20) -> Optional[Dict]:
    """
    Simple sweep detector: price takes out a recent swing then closes back inside.
    Returns side and level if found on the latest bars.
    """
    df = detect_swings(df)
    recent = df.iloc[-lookback:]
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # Sell-side liquidity sweep (bullish potential)
    recent_lows = recent["swing_low"].dropna()
    if not recent_lows.empty:
        ssl = recent_lows.iloc[-1]
        if prev["low"] < ssl and last["close"] > ssl:
            return {"side": "bull", "level": float(ssl), "type": "ssl_sweep"}

    # Buy-side liquidity sweep (bearish potential)
    recent_highs = recent["swing_high"].dropna()
    if not recent_highs.empty:
        bsl = recent_highs.iloc[-1]
        if prev["high"] > bsl and last["close"] < bsl:
            return {"side": "bear", "level": float(bsl), "type": "bsl_sweep"}

    return None


def detect_mss(df: pd.DataFrame, bias: str, lookback: int = 10) -> bool:
    """
    Very simplified Market Structure Shift.
    For bull bias: recent higher high after a low.
    Expand with proper swing sequence tracking for production.
    """
    recent = df.iloc[-lookback:]
    if bias == "bull":
        return recent["high"].iloc[-1] > recent["high"].iloc[:-1].max()
    else:
        return recent["low"].iloc[-1] < recent["low"].iloc[:-1].min()


def generate_ict_signal(df_15: pd.DataFrame, df_5: pd.DataFrame, as_of=None) -> Optional[Dict[str, Any]]:
    """
    Core ICT sequence – price concepts + time confluence working TOGETHER.
    1. Liquidity sweep on 15m
    2. Structure shift confirmation
    3. Price in discount/premium appropriately
    4. Presence of FVG or recent displacement
    5. Time score from multi-window kill zones (soft, additive)
    """
    from src.utils import time_score, get_active_windows, time_context
    from config.settings import MIN_TIME_SCORE, REQUIRE_PRIMARY_WINDOW
    from src.utils import is_high_probability_time

    if len(df_15) < 50 or len(df_5) < 30:
        return None

    # --- Time layer (soft) ---
    t_score = time_score(as_of)
    active_windows = get_active_windows(as_of)
    t_ctx = time_context(as_of)

    if REQUIRE_PRIMARY_WINDOW and not is_high_probability_time():
        return None
    if t_score < MIN_TIME_SCORE:
        return None

    # --- Price concepts (unchanged core) ---
    df_15 = detect_fvg(detect_swings(df_15))
    sweep = detect_liquidity_sweep(df_15)
    if not sweep:
        return None

    bias = sweep["side"]
    if not detect_mss(df_5, bias):
        return None

    pd_info = premium_discount(df_15)
    if bias == "bull" and pd_info["zone"] != "discount":
        return None
    if bias == "bear" and pd_info["zone"] != "premium":
        return None

    last_close = float(df_15["close"].iloc[-1])
    stop = sweep["level"] * (0.998 if bias == "bull" else 1.002)
    target = pd_info["range_high"] if bias == "bull" else pd_info["range_low"]

    entry_zone = last_close
    if bias == "bull":
        fvgs = df_15["bull_fvg_bot"].dropna()
        if not fvgs.empty:
            entry_zone = float(fvgs.iloc[-1])
    else:
        fvgs = df_15["bear_fvg_top"].dropna()
        if not fvgs.empty:
            entry_zone = float(fvgs.iloc[-1])

    # Combined confluence: price rules (base) + time score
    # Base price confluence assumed 0.70 when all price filters pass
    price_score = 0.70
    combined = min(1.0, price_score + (t_score * 0.30))

    reason_parts = [
        sweep["type"],
        "MSS",
        f"{pd_info['zone']} FVG/OB",
    ]
    if active_windows:
        reason_parts.append(f"time[{'+'.join(active_windows)}]")
    reason_parts.append(f"t_score={t_score:.2f}")

    signal = {
        "bias": bias,
        "entry_zone": entry_zone,
        "stop": stop,
        "target": target,
        "sweep_level": sweep["level"],
        "pd_zone": pd_info["zone"],
        "underlying_price": last_close,
        "time_score": t_score,
        "active_windows": active_windows,
        "combined_score": round(combined, 2),
        "time_context": t_ctx,
        "reason": " + ".join(reason_parts),
    }

    # Dealing Range + Octants + CE (ICT consolidation-day rules) – additive
    try:
        from src.dealing_range import compute_dealing_range, refine_entry_with_ce_and_octants
        dealing = compute_dealing_range(df_15)
        signal = refine_entry_with_ce_and_octants(signal, dealing, df_15)
        if dealing:
            reason_parts.append(f"DR[{dealing.get('source', 'pm')}]")
            signal["reason"] = " + ".join(reason_parts)
    except Exception as e:
        logger.warning(f"Dealing-range enrichment failed for {df_15}: {e}")

    # Body imbalances + Order Block + key wick mid (Monday Review rules) – additive
    try:
        from src.imbalance import enrich_with_imbalance_and_ob
        signal = enrich_with_imbalance_and_ob(signal, df_15)
        if signal.get("body_imbalance"):
            reason_parts.append("body_imb")
        if signal.get("order_block"):
            reason_parts.append("OB")
        signal["reason"] = " + ".join(reason_parts)
        signal["combined_score"] = round(signal.get("combined_score", combined), 2)
    except Exception as e:
        logger.warning(f"Imbalance/order-block enrichment failed: {e}")

    # Opening Range Gap + FPFVG + Wick-as-imbalance (High of Day Review) – additive
    try:
        from src.opening_range import enrich_with_org_and_fpfvg
        signal = enrich_with_org_and_fpfvg(signal, df_15)
        if signal.get("opening_range_gap"):
            reason_parts.append("ORG")
        if signal.get("fpfvg"):
            reason_parts.append("FPFVG")
        if signal.get("wick_imbalance"):
            reason_parts.append("wick_imb")
        signal["reason"] = " + ".join(reason_parts)
        signal["combined_score"] = round(signal.get("combined_score", combined), 2)
    except Exception as e:
        logger.warning(f"Opening-range enrichment failed: {e}")

    # Seek & Destroy profile – additive risk context
    try:
        from src.seek_destroy import enrich_with_seek_destroy
        signal = enrich_with_seek_destroy(signal, df_15)
        if signal.get("snd_warning"):
            reason_parts.append("SND_WARN")
            signal["reason"] = " + ".join(reason_parts)
        signal["combined_score"] = round(signal.get("combined_score", combined), 2)
    except Exception as e:
        logger.warning(f"Seek & Destroy enrichment failed: {e}")

    # Chain of Custody of Price – additive target / confluence layer
    try:
        from src.chain_of_custody import enrich_with_chain_of_custody
        signal = enrich_with_chain_of_custody(signal, df_15)
        if signal.get("chain_of_custody"):
            reason_parts.append("CoC")
            signal["reason"] = " + ".join(reason_parts)
        signal["combined_score"] = round(signal.get("combined_score", combined), 2)
    except Exception as e:
        logger.warning(f"Chain-of-Custody enrichment failed: {e}")

    return signal






