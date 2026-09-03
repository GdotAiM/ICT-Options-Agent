"""
ICT Chain of Custody of Price
From the lecture of the same name.

Idea: price is handed from one high-probability PD array to the next
in a logical sequence toward a draw on liquidity.
We already detect FVG / body imbalance / OB / CE / octants.
This module stitches the nearest unmitigated arrays into a simple chain
and sets a "next custody level" (target) that the agent can use.
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List
import pandas as pd
from loguru import logger


def _collect_pd_arrays(signal: Dict[str, Any], df: pd.DataFrame) -> List[Dict]:
    """Gather PD-array style levels already present on the signal + fresh ones.
    Now also includes graded RTH ORG and daily-inefficiency levels (both videos).
    """
    arrays = []

    # From existing enrichments
    if signal.get("fpfvg"):
        f = signal["fpfvg"]
        arrays.append({
            "kind": "fpfvg",
            "top": f["top"],
            "bot": f["bot"],
            "ce": f["ce"],
            "side": "bull" if "bull" in f["type"] else "bear",
        })
    if signal.get("body_imbalance"):
        b = signal["body_imbalance"]
        arrays.append({
            "kind": "body_imb",
            "top": b["top"],
            "bot": b["bot"],
            "ce": b["mid"],
            "side": "bull" if "bull" in b["type"] else "bear",
        })
    if signal.get("order_block"):
        o = signal["order_block"]
        arrays.append({
            "kind": "ob",
            "top": o["high"],
            "bot": o["low"],
            "ce": o["mid"],
            "side": "bull" if "bull" in o["type"] else "bear",
        })
    if signal.get("wick_imbalance"):
        w = signal["wick_imbalance"]
        arrays.append({
            "kind": "wick_imb",
            "top": max(w["body"], w["extreme"]),
            "bot": min(w["body"], w["extreme"]),
            "ce": w["ce"],
            "side": "bear" if "high" in w["type"] else "bull",
        })

    # Graded RTH ORG levels (Chain of Custody With RTH ORG)
    if signal.get("rth_org") and signal["rth_org"].get("graded"):
        g = signal["rth_org"]["graded"]
        for key, side in (("ce", "neutral"), ("q1", "bull"), ("q3", "bear"), ("o3", "bull"), ("o5", "bear")):
            if key in g:
                arrays.append({
                    "kind": f"rth_org_{key}",
                    "top": g[key],
                    "bot": g[key],
                    "ce": g[key],
                    "side": side if side != "neutral" else ("bull" if signal.get("bias") == "bull" else "bear"),
                })

    # Daily inefficiency graded levels (Chain of Custody With Daily Inefficiencies)
    if signal.get("daily_inefficiency") and signal["daily_inefficiency"].get("graded"):
        g = signal["daily_inefficiency"]["graded"]
        for key in ("ce", "q1", "q3", "o1", "o7"):
            if key in g:
                arrays.append({
                    "kind": f"daily_ineff_{key}",
                    "top": g[key],
                    "bot": g[key],
                    "ce": g[key],
                    "side": "bull" if key in ("q1", "o1", "ce") else "bear",
                })

    # Simple draw-on-liquidity proxies: recent swing high / low
    if len(df) >= 20:
        recent = df.iloc[-40:]
        swing_hi = float(recent["high"].max())
        swing_lo = float(recent["low"].min())
        arrays.append({"kind": "swing_hi", "top": swing_hi, "bot": swing_hi, "ce": swing_hi, "side": "bear"})
        arrays.append({"kind": "swing_lo", "top": swing_lo, "bot": swing_lo, "ce": swing_lo, "side": "bull"})

    return arrays



def build_chain(signal: Dict[str, Any], df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """
    Build a simple chain-of-custody view.
    Returns current level being respected + next draw target.
    """
    bias = signal.get("bias", "bull")
    price = signal.get("underlying_price", 0)
    if not price:
        return None

    arrays = _collect_pd_arrays(signal, df)
    if not arrays:
        return None

    # Filter arrays that still make sense for the bias
    if bias == "bull":
        # we care about support-style arrays below or near price, and upside targets
        supports = [a for a in arrays if a["side"] == "bull" and a["ce"] <= price * 1.002]
        targets = [a for a in arrays if a["ce"] > price]
    else:
        supports = [a for a in arrays if a["side"] == "bear" and a["ce"] >= price * 0.998]
        targets = [a for a in arrays if a["ce"] < price]

    # nearest support (current custody)
    current = None
    if supports:
        current = min(supports, key=lambda a: abs(a["ce"] - price))

    # nearest target in the direction of bias (next custody)
    next_target = None
    if targets:
        next_target = min(targets, key=lambda a: abs(a["ce"] - price))

    if not current and not next_target:
        return None

    return {
        "current_custody": current,
        "next_custody": next_target,
        "bias": bias,
        "note": "price expected to travel current → next along graded PD arrays",
    }


def enrich_with_chain_of_custody(
    signal: Dict[str, Any],
    df_15: pd.DataFrame,
) -> Dict[str, Any]:
    """Additive enrichment – never overrides core signal."""
    if not signal:
        return signal
    out = dict(signal)

    chain = build_chain(signal, df_15)
    if not chain:
        return out

    out["chain_of_custody"] = chain

    # Soft boost when we have a clear next target aligned with bias
    if chain.get("next_custody"):
        out["combined_score"] = min(1.0, out.get("combined_score", 0.7) + 0.04)
        # refine target if not already set aggressively
        nxt = chain["next_custody"]["ce"]
        if signal.get("bias") == "bull":
            out["target"] = max(signal.get("target", nxt), nxt)
        else:
            out["target"] = min(signal.get("target", nxt), nxt)

    if chain.get("current_custody"):
        # if price is sitting on the current CE, small boost
        price = signal.get("underlying_price", 0)
        ce = chain["current_custody"]["ce"]
        if price and abs(price - ce) / max(price, 1) < 0.002:
            out["combined_score"] = min(1.0, out.get("combined_score", 0.7) + 0.03)

    return out
