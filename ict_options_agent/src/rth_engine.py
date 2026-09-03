"""
RTH (Regular Trading Hours) Session Engine.

This is the primary signal-generation framework for the ICT RTH Options Agent.
Instead of requiring a textbook MSS sequence, the RTH engine builds a structured
market state from:

  - Prior RTH settlement vs 09:30 open (ORG)
  - Opening Range (09:30–10:00)
  - Overnight / pre-open liquidity
  - Session phase (AM / Lunch / PM)
  - Displacement and FVG evidence
  - Liquidity delivery direction

MSS is demoted from hard gate to one piece of structural evidence (5% weight).
The RTH state is consumed by the AI thesis agent to reason about
expansion / reversal / continuation / repricing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, time
import pandas as pd
import numpy as np
import pytz
from loguru import logger

ET = pytz.timezone("US/Eastern")

# ── Session phases ──────────────────────────────────────────────
PRE_OPEN   = "pre_open"
RTH_AM     = "rth_am"       # 09:30 – 12:00
RTH_LUNCH  = "rth_lunch"    # 12:00 – 13:30
RTH_PM     = "rth_pm"       # 13:30 – 16:00
POST_CLOSE = "post_close"

# Opening range window (ET)
OR_START = time(9, 30)
OR_END   = time(10, 0)

# Session boundaries (ET)
RTH_OPEN_TIME  = time(9, 30)
RTH_CLOSE_TIME = time(16, 0)
LUNCH_START    = time(12, 0)
LUNCH_END      = time(13, 30)


def get_session_phase(et: Optional[datetime] = None) -> str:
    """Return the current RTH session phase."""
    if et is None:
        et = datetime.now(ET)
    t = et.time()
    if t < RTH_OPEN_TIME:
        return PRE_OPEN
    if t < LUNCH_START:
        return RTH_AM
    if t < LUNCH_END:
        return RTH_LUNCH
    if t < RTH_CLOSE_TIME:
        return RTH_PM
    return POST_CLOSE


def is_rth(et: Optional[datetime] = None) -> bool:
    """True if inside regular trading hours (09:30–16:00 ET)."""
    phase = get_session_phase(et)
    return phase in (RTH_AM, RTH_LUNCH, RTH_PM)


# ── Opening Range ───────────────────────────────────────────────

def build_opening_range(df_1m: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """
    Build the 09:30–10:00 ET opening range from 1-minute bars.

    Returns dict with OR high, low, mid, and expansion status.
    Returns None if the opening range hasn't formed yet.
    """
    if df_1m is None or len(df_1m) < 2:
        return None

    # Ensure index is tz-aware
    idx = df_1m.index
    if idx.tz is None:
        idx = idx.tz_localize(ET, ambiguous="infer", nonexistent="shift_forward")
        df_1m = df_1m.copy()
        df_1m.index = idx
    elif str(idx.tz) != "US/Eastern":
        df_1m = df_1m.copy()
        df_1m.index = idx.tz_convert(ET)

    # Filter to 09:30–10:00
    times = df_1m.index.time
    or_mask = (times >= OR_START) & (times < OR_END)
    or_bars = df_1m[or_mask]

    if len(or_bars) < 2:
        return None

    or_high = float(or_bars["high"].max())
    or_low  = float(or_bars["low"].min())
    or_mid  = (or_high + or_low) / 2.0

    # Check for expansion after 10:00
    after_or = df_1m[df_1m.index.time >= OR_END]
    last_close = float(df_1m["close"].iloc[-1])

    expansion = "none"
    if len(after_or) > 0:
        if last_close > or_high:
            expansion = "up"
        elif last_close < or_low:
            expansion = "down"

    return {
        "high": or_high,
        "low": or_low,
        "mid": or_mid,
        "range": or_high - or_low,
        "expansion": expansion,
        "bar_count": len(or_bars),
    }


# ── ORG (Opening Range Gap) ─────────────────────────────────────

def build_org(
    prior_rth_close: Optional[float],
    rth_open: Optional[float],
) -> Optional[Dict[str, Any]]:
    """
    Opening Range Gap: prior RTH settlement vs 09:30 open.

    Grades the gap into octants/quadrants/CE for the AI to reason about
    repricing toward mid-gap.
    """
    if prior_rth_close is None or rth_open is None:
        return None

    gap = rth_open - prior_rth_close
    if abs(gap) < 1e-6:
        return {
            "type": "none",
            "prior_close": prior_rth_close,
            "rth_open": rth_open,
            "gap": 0.0,
            "mid": prior_rth_close,
            "direction": "none",
            "ce": prior_rth_close,
        }

    high = max(prior_rth_close, rth_open)
    low  = min(prior_rth_close, rth_open)
    rng  = high - low

    return {
        "type": "premium" if gap > 0 else "discount",
        "prior_close": prior_rth_close,
        "rth_open": rth_open,
        "gap": gap,
        "gap_pct": gap / prior_rth_close if prior_rth_close else 0,
        "mid": (prior_rth_close + rth_open) / 2.0,
        "direction": "up" if gap > 0 else "down",
        "ce": (high + low) / 2.0,
        "q1": low + rng * 0.25,
        "q3": low + rng * 0.75,
        "high": high,
        "low": low,
    }


# ── Overnight / Pre-open Liquidity ──────────────────────────────

def build_overnight_liquidity(df_1m: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """
    Track pre-09:30 bars as overnight liquidity reference.

    With same-day-only data, this captures the pre-open session if available.
    Returns None if no pre-open bars exist.
    """
    if df_1m is None or len(df_1m) < 2:
        return None

    idx = df_1m.index
    if idx.tz is None:
        idx = idx.tz_localize(ET, ambiguous="infer", nonexistent="shift_forward")
        df_1m = df_1m.copy()
        df_1m.index = idx
    elif str(idx.tz) != "US/Eastern":
        df_1m = df_1m.copy()
        df_1m.index = idx.tz_convert(ET)

    pre_open = df_1m[df_1m.index.time < RTH_OPEN_TIME]
    if len(pre_open) < 2:
        return None

    return {
        "high": float(pre_open["high"].max()),
        "low": float(pre_open["low"].min()),
        "close": float(pre_open["close"].iloc[-1]),
    }


# ── Displacement Detection ──────────────────────────────────────

def detect_displacement(df: pd.DataFrame, lookback: int = 5) -> Optional[Dict[str, Any]]:
    """
    Detect displacement: a strong directional move over `lookback` bars.

    Measures the range expansion relative to average bar range.
    """
    if df is None or len(df) < lookback + 2:
        return None

    recent = df.iloc[-lookback:]
    avg_range = float(df["high"].sub(df["low"]).iloc[:-lookback].mean())
    if avg_range <= 0:
        return None

    move = float(recent["close"].iloc[-1] - recent["open"].iloc[0])
    total_range = float(recent["high"].max() - recent["low"].min())
    expansion_ratio = total_range / avg_range if avg_range > 0 else 0

    if expansion_ratio < 1.3:
        return None

    direction = "bull" if move > 0 else "bear"
    return {
        "direction": direction,
        "move": move,
        "range": total_range,
        "expansion_ratio": round(expansion_ratio, 2),
        "bars": lookback,
    }


# ── FVG Detection (reused from ict_detectors) ───────────────────

def detect_fvgs(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Detect all Fair Value Gaps in the recent window.
    Returns a list of FVG dicts (bull and bear).
    """
    if df is None or len(df) < 3:
        return []

    fvgs = []
    window = df.iloc[-80:] if len(df) > 80 else df

    for i in range(2, len(window)):
        c_prev2 = window.iloc[i - 2]
        c_curr = window.iloc[i]

        # Bullish FVG: high[i-2] < low[i]
        if float(c_prev2["high"]) < float(c_curr["low"]):
            fvgs.append({
                "type": "bull",
                "top": float(c_curr["low"]),
                "bot": float(c_prev2["high"]),
                "ce": (float(c_curr["low"]) + float(c_prev2["high"])) / 2,
                "bar_offset": len(window) - i,
            })

        # Bearish FVG: low[i-2] > high[i]
        if float(c_prev2["low"]) > float(c_curr["high"]):
            fvgs.append({
                "type": "bear",
                "top": float(c_prev2["low"]),
                "bot": float(c_curr["high"]),
                "ce": (float(c_prev2["low"]) + float(c_curr["high"])) / 2,
                "bar_offset": len(window) - i,
            })

    return fvgs


# ── Liquidity Sweep (RTH-aware) ─────────────────────────────────

def detect_liquidity_delivery(
    df: pd.DataFrame,
    overnight: Optional[Dict[str, Any]] = None,
    opening_range: Optional[Dict[str, Any]] = None,
    lookback: int = 20,
) -> Optional[Dict[str, Any]]:
    """
    Detect liquidity delivery: price taking out a key level and reacting.

    Checks overnight high/low and OR high/low as liquidity targets.
    Returns the sweep event with direction and level.
    """
    if df is None or len(df) < 3:
        return None

    recent = df.iloc[-lookback:] if len(df) >= lookback else df
    last = df.iloc[-1]
    prev = df.iloc[-2]
    last_close = float(last["close"])

    # Build liquidity targets
    targets: List[Tuple[str, float, str]] = []  # (name, level, side_when_swept)

    if overnight:
        targets.append(("overnight_high", overnight["high"], "bear"))
        targets.append(("overnight_low", overnight["low"], "bull"))

    if opening_range:
        targets.append(("or_high", opening_range["high"], "bear"))
        targets.append(("or_low", opening_range["low"], "bull"))

    # Also use recent swing extremes
    recent_high = float(recent["high"].max())
    recent_low = float(recent["low"].min())
    targets.append(("recent_high", recent_high, "bear"))
    targets.append(("recent_low", recent_low, "bull"))

    prev_high = float(prev["high"])
    prev_low = float(prev["low"])

    for name, level, side in targets:
        if side == "bull":
            # Sell-side liquidity sweep: prev takes out the level, last closes back above
            if prev_low <= level and last_close > level:
                return {
                    "side": "bull",
                    "level": level,
                    "target_name": name,
                    "type": "ssl_sweep",
                }
        else:
            # Buy-side liquidity sweep: prev takes out the level, last closes back below
            if prev_high >= level and last_close < level:
                return {
                    "side": "bear",
                    "level": level,
                    "target_name": name,
                    "type": "bsl_sweep",
                }

    # Also detect acceptance (price holding above/below a key level)
    for name, level, side in targets:
        if side == "bull" and last_close > level and prev_low <= level:
            return {
                "side": "bull",
                "level": level,
                "target_name": name,
                "type": "ssl_acceptance",
            }
        if side == "bear" and last_close < level and prev_high >= level:
            return {
                "side": "bear",
                "level": level,
                "target_name": name,
                "type": "bsl_acceptance",
            }

    return None


# ── MSS Detection (now evidence, not gate) ──────────────────────

def detect_mss_evidence(df: pd.DataFrame, bias: str, lookback: int = 10) -> bool:
    """
    Simplified Market Structure Shift — now returns a boolean evidence flag.
    """
    if df is None or len(df) < lookback:
        return False
    recent = df.iloc[-lookback:]
    if bias == "bull":
        return float(recent["high"].iloc[-1]) > float(recent["high"].iloc[:-1].max())
    else:
        return float(recent["low"].iloc[-1]) < float(recent["low"].iloc[:-1].min())


# ── Premium / Discount ──────────────────────────────────────────

def premium_discount(df: pd.DataFrame, lookback: int = 50) -> Dict[str, Any]:
    """Compute premium/discount zone relative to recent range."""
    if df is None or len(df) < 5:
        return {"zone": "neutral", "mid": 0, "range_high": 0, "range_low": 0}
    recent = df.iloc[-lookback:] if len(df) >= lookback else df
    rh = float(recent["high"].max())
    rl = float(recent["low"].min())
    mid = (rh + rl) / 2.0
    last = float(df["close"].iloc[-1])
    zone = "discount" if last < mid else "premium"
    return {"zone": zone, "mid": mid, "range_high": rh, "range_low": rl}


# ── Full RTH Market State ───────────────────────────────────────

def build_rth_state(
    df_1m: pd.DataFrame,
    df_5m: pd.DataFrame,
    df_15m: pd.DataFrame,
    prior_rth_close: Optional[float] = None,
    symbol: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Build the complete RTH market state for AI consumption.

    This is the primary output of the RTH engine. It replaces the old
    MSS-gated signal with a structured market state that the AI can
    reason about.
    """
    if df_1m is None or len(df_1m) < 5:
        return None

    et = datetime.now(ET)
    session = get_session_phase(et)

    # Only generate state during RTH
    if session not in (RTH_AM, RTH_LUNCH, RTH_PM):
        return None

    # 09:30 open
    rth_open_bars = df_1m[df_1m.index.time == RTH_OPEN_TIME] if df_1m.index.tz else df_1m
    rth_open = float(rth_open_bars["open"].iloc[0]) if len(rth_open_bars) > 0 else float(df_1m["open"].iloc[0])

    # Prior RTH close
    if prior_rth_close is None:
        # Fallback: use the first bar's open as a proxy if no prior close
        prior_rth_close = rth_open

    # Build components
    org = build_org(prior_rth_close, rth_open)
    opening_range = build_opening_range(df_1m)
    overnight = build_overnight_liquidity(df_1m)
    displacement = detect_displacement(df_5m) if df_5m is not None else None
    fvgs = detect_fvgs(df_15m) if df_15m is not None else []
    liquidity = detect_liquidity_delivery(df_5m, overnight, opening_range)
    pd_info = premium_discount(df_15m) if df_15m is not None else {"zone": "neutral"}

    # MSS as evidence (not gate)
    bias_hint = "bull" if (liquidity and liquidity["side"] == "bull") else "bear" if (liquidity and liquidity["side"] == "bear") else "neutral"
    mss = detect_mss_evidence(df_5m, bias_hint) if df_5m is not None else False

    # First presented FVG
    fpfvg = fvgs[0] if fvgs else None

    # OR expansion / rejection
    or_status = "forming"
    if opening_range:
        or_status = opening_range.get("expansion", "none")

    # Last price
    last_close = float(df_1m["close"].iloc[-1])

    # Build confluence score (RTH-weighted)
    score = 0.0
    score_breakdown = {}

    # RTH context (20%)
    session_weight = {RTH_AM: 0.20, RTH_LUNCH: 0.08, RTH_PM: 0.15}
    ctx_score = session_weight.get(session, 0.0)
    score += ctx_score
    score_breakdown["rth_context"] = round(ctx_score, 2)

    # Liquidity (20%)
    liq_score = 0.20 if liquidity else 0.0
    score += liq_score
    score_breakdown["liquidity"] = round(liq_score, 2)

    # ORG (15%)
    org_score = 0.0
    if org and org.get("type") != "none":
        # Price near mid-gap or CE
        mid = org.get("mid", 0)
        ce = org.get("ce", 0)
        if last_close and abs(last_close - mid) / max(last_close, 1) < 0.003:
            org_score = 0.15
        elif last_close and abs(last_close - ce) / max(last_close, 1) < 0.003:
            org_score = 0.12
        elif org.get("direction") != "none":
            org_score = 0.08
    score += org_score
    score_breakdown["org"] = round(org_score, 2)

    # PD Array (10%)
    pd_score = 0.10 if pd_info.get("zone") in ("premium", "discount") else 0.0
    score += pd_score
    score_breakdown["pd_array"] = round(pd_score, 2)

    # Displacement (15%)
    disp_score = 0.15 if displacement else 0.0
    score += disp_score
    score_breakdown["displacement"] = round(disp_score, 2)

    # FVG (10%)
    fvg_score = 0.10 if fvgs else 0.0
    score += fvg_score
    score_breakdown["fvg"] = round(fvg_score, 2)

    # MSS (5%)
    mss_score = 0.05 if mss else 0.0
    score += mss_score
    score_breakdown["mss"] = round(mss_score, 2)

    score = round(min(1.0, score), 2)

    # Determine bias from evidence
    bias = "neutral"
    if liquidity:
        bias = liquidity["side"]
    elif displacement:
        bias = displacement["direction"]
    elif opening_range and opening_range.get("expansion") in ("up", "down"):
        bias = "bull" if opening_range["expansion"] == "up" else "bear"
    elif org and org.get("direction") != "none":
        bias = "bull" if org["direction"] == "up" else "bear"

    # Build the structured state
    state = {
        "symbol": symbol,
        "session": session,
        "timestamp_et": et.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "last_price": last_close,
        "bias": bias,
        "combined_score": score,
        "score_breakdown": score_breakdown,
        "rth_open": rth_open,
        "prior_rth_close": prior_rth_close,
        "org": org,
        "opening_range": opening_range,
        "overnight": overnight,
        "liquidity": liquidity,
        "displacement": displacement,
        "fvgs": fvgs[:5],  # cap for prompt size
        "first_presented_fvg": fpfvg,
        "mss": mss,
        "pd_zone": pd_info.get("zone"),
        "pd_mid": pd_info.get("mid"),
        "pd_range_high": pd_info.get("range_high"),
        "pd_range_low": pd_info.get("range_low"),
        "or_status": or_status,
    }

    # Build reason string
    parts = []
    if session:
        parts.append(f"session[{session}]")
    if org and org.get("direction") != "none":
        parts.append(f"ORG_{org['direction']}")
    if opening_range:
        parts.append(f"OR_{or_status}")
    if liquidity:
        parts.append(f"{liquidity['type']}@{liquidity['target_name']}")
    if displacement:
        parts.append(f"disp_{displacement['direction']}")
    if fvgs:
        parts.append(f"FVGx{len(fvgs)}")
    if mss:
        parts.append("MSS")
    parts.append(f"PD_{pd_info.get('zone', '?')}")
    parts.append(f"score={score:.2f}")
    state["reason"] = " + ".join(parts)

    return state