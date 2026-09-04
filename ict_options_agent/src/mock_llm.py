"""
Mock LLM for ICT Options Agent — provides intelligent decisions without OpenAI.

Set MOCK_LLM=true in .env to activate.  Decisions are derived from the actual
ICT evidence packet (scores, bias, pattern flags) rather than being a dumb
deterministic fallback.

Thesis & reasoning are grounded in the real signal data — no hallucinated
strikes, premiums or Greeks.
"""
from __future__ import annotations

import os
import random
from typing import Any, Dict, Optional


random.seed(int(os.getenv("MOCK_SEED", "42")))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _score_threshold(rth: bool = False) -> tuple[float, float]:
    """Return (min_confluence, min_time) based on whether we're in RTH mode."""
    if rth:
        return 0.35, 0.25  # RTH uses softer gates
    return 0.55, 0.35


def _pick_reason(signal: Dict[str, Any], rth_state: Optional[Dict[str, Any]] = None) -> str:
    """Generate a context-aware narrative from the evidence."""
    reasons = []

    bias = signal.get("bias", "")
    sweep = signal.get("sweep_level")
    mss = signal.get("mss", False)
    fvg = signal.get("fpfvg") or signal.get("fvg")
    pd_zone = signal.get("pd_zone", "")
    window = signal.get("active_windows", [])
    displacement = signal.get("displacement", False)
    snd = bool(signal.get("snd_warning", False))

    if bias == "bull":
        direction = "bullish"
        sweep_note = f"sweep of {sweep}" if sweep else "liquidity sweep detected"
        reasons.append(f"{sweep_note}, ")
    else:
        direction = "bearish"
        sweep_note = f"sweep of {sweep}" if sweep else "liquidity sweep detected"
        reasons.append(f"{sweep_note}, ")

    if mss:
        reasons.append("confirmed market-structure shift, ")
    if fvg:
        reasons.append(f"FVG at {fvg}, ")
    if pd_zone:
        reasons.append(f"in {pd_zone} zone, ")
    if displacement:
        reasons.append("with strong displacement, ")

    active = signal.get("active_windows", [])
    if active:
        reasons.append(f"during {'/'.join(active[:2])} window")
    elif rth_state:
        session = rth_state.get("session", "")
        if session:
            reasons.append(f"during {session}")

    narrative = "".join(reasons).rstrip(", ") + "."
    return narrative if narrative else "ICT evidence supports the directional thesis."


def _classify_thesis(signal: Dict[str, Any], rth_state: Optional[Dict[str, Any]] = None) -> str:
    """Classify into EXPANSION / REVERSAL / CONTINUATION / REPRICING / RANGE."""
    sweep = signal.get("sweep_level")
    rejection = signal.get("reason", "").lower()
    displacement = signal.get("displacement", False)
    score = float(signal.get("combined_score", rth_state.get("combined_score", 0) if rth_state else 0))
    bias = signal.get("bias", "")
    pd_mid = (rth_state or {}).get("pd_mid")
    price = signal.get("underlying_price", 0)

    # Reversal: sweep + rejection language
    if sweep and ("rejection" in rejection or "reject" in rejection.lower()):
        return "REVERSAL"
    # Expansion: strong displacement + high score
    if displacement and score >= 0.6:
        return "EXPANSION"
    # Continuation: established trend in PM
    session = (rth_state or {}).get("session", "")
    if session == "rth_pm" and score >= 0.4:
        return "CONTINUATION"
    # Repricing: near mid or low momentum
    if pd_mid and price:
        ratio = price / pd_mid
        if 0.95 < ratio < 1.05:
            return "REPRICING"
    # Default by score
    if score < 0.35:
        return "RANGE"
    return "EXPANSION"


def _build_decision(
    signal: Dict[str, Any],
    options_evidence: Optional[Dict[str, Any]],
    rth_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Core mock decision logic — grounded in ICT evidence, not random."""
    score = float(signal.get("combined_score", rth_state.get("combined_score", 0.0) if rth_state else 0.0))
    time_score = float(signal.get("time_score", 0.0))
    bias = signal.get("bias", "neutral")
    snd = bool(signal.get("snd_warning", False))
    chain = options_evidence or {}

    min_score, min_time = _score_threshold(rth_state is not None)

    blockers: list[str] = []
    if score < min_score:
        blockers.append(f"confluence score {score:.2f} below threshold {min_score}")
    if time_score < min_time:
        blockers.append(f"time score {time_score:.2f} below threshold {min_time}")
    if snd:
        blockers.append("Seek & Destroy warning — liquidity trap likely")
    if rth_state and rth_state.get("session") == "rth_lunch":
        blockers.append("lunch session — reduced confidence")
    if not chain.get("available") and chain.get("reason"):
        blockers.append(f"options chain unavailable: {chain.get('reason')}")

    decision = "WAIT" if blockers else "TRADE"
    strategy_map = {"bull": "BULL_CALL_SPREAD", "bear": "BEAR_PUT_SPREAD"}
    strategy = strategy_map.get(bias, "NONE")

    if decision == "WAIT":
        rationale = "; ".join(blockers)
    else:
        rationale = _pick_reason(signal, rth_state)

    thesis = _classify_thesis(signal, rth_state) if rth_state or any(k in signal for k in ("sweep_level", "mss")) else None

    result: Dict[str, Any] = {
        "decision": decision,
        "approve": decision == "TRADE",
        "direction": bias,
        "options_strategy": strategy,
        "confidence": round(max(0.0, min(1.0, score)), 2),
        "ict_thesis": rationale,
        "required_confluences": ["liquidity sweep", "MSS", "PD location", "time"],
        "missing_confluences": blockers,
        "entry_condition": "Execute only after deterministic quote and risk gates pass.",
        "invalidation": signal.get("stop"),
        "target": signal.get("target"),
        "rationale": rationale,
        "source": "mock_ict_agent",
        "model": None,
    }

    if thesis:
        result["thesis_model"] = thesis

    # DTE and moneyness guidance from evidence
    preferred_dte = signal.get("ai_options_dte_target", 7)
    if isinstance(preferred_dte, (int, float)):
        preferred_dte = max(3, min(21, int(preferred_dte)))
    result["preferred_dte"] = preferred_dte
    result["preferred_moneyness"] = "ATM_to_slightly_ITM"
    result["chain_requirements"] = ["tight quotes (<25% spread)", "adequate open interest (>50)"]

    return result


def _build_challenge(proposal: Dict[str, Any], signal: Dict[str, Any]) -> Dict[str, Any]:
    """Adversarial review — flag real risks from the evidence."""
    blockers = proposal.get("missing_confluences", [])
    snd = bool(signal.get("snd_warning", False))

    contradictions = []
    fatal_risks = []

    if snd:
        fatal_risks.append("Seek & Destroy pattern detected — price likely targeting the sweep level before reversing")
    if any("lunch" in b.lower() for b in blockers):
        contradictions.append("Lunch session reduces directional conviction")
    if any("time score" in b.lower() for b in blockers):
        contradictions.append("Outside optimal time window — execution risk higher")

    verdict = "PASS" if not fatal_risks and len(contradictions) <= 1 else "FAIL"
    if verdict == "FAIL" and not fatal_risks:
        verdict = "PASS"  # soft warnings don't kill

    return {
        "verdict": verdict,
        "confidence": round(max(0.3, 1.0 - len(fatal_risks) * 0.4 - len(contradictions) * 0.1), 2),
        "contradictions": contradictions,
        "fatal_risks": fatal_risks,
        "reason": "; ".join(fatal_risks or contradictions) or "No material contradictions found.",
        "source": "mock_adversarial_challenger",
        "model": None,
    }


# ── Public entry points (must match real LLM signatures) ─────────────────────

def call_openai(
    signal: Dict[str, Any],
    options_evidence: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Primary trade-decision mock — replaces _call_openai."""
    try:
        return _build_decision(signal, options_evidence)
    except Exception as e:
        from loguru import logger
        logger.warning(f"Mock ICT agent error: {e}")
        return None


def call_rth_openai(
    rth_state: Dict[str, Any],
    options_evidence: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """RTH market-state mock — replaces _call_rth_openai."""
    try:
        return _build_decision(rth_state, options_evidence, rth_state=rth_state)
    except Exception as e:
        from loguru import logger
        logger.warning(f"Mock RTH agent error: {e}")
        return None


def call_challenge_openai(
    signal: Dict[str, Any],
    proposal: Dict[str, Any],
    options_evidence: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Adversarial challenge mock — replaces _challenge_openai."""
    try:
        return _build_challenge(proposal, signal)
    except Exception as e:
        from loguru import logger
        logger.warning(f"Mock challenger error: {e}")
        return None


def call_rth_challenge(
    rth_state: Dict[str, Any],
    proposal: Dict[str, Any],
    options_evidence: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """RTH adversarial challenge mock — replaces _challenge_rth_openai."""
    return call_challenge_openai(rth_state, proposal, options_evidence)


def reassess_position(
    context: Dict[str, Any],
    position: Dict[str, Any],
) -> Dict[str, Any]:
    """Post-trade monitor mock — replaces reassess_open_position."""
    try:
        plpc = position.get("unrealized_plpc")
        if plpc is None:
            return {"verdict": "UNAVAILABLE", "action": "HOLD", "reason": "No P&L data available", "source": "mock_post_trade"}

        pl = float(plpc)
        if pl >= 0.40:
            action = "EXIT"
            reason = f"+{pl*100:.0f}% P&L — target zone reached"
        elif pl >= 0.20:
            action = "HOLD"
            reason = f"+{pl*100:.0f}% P&L — thesis still valid, holding for further extension"
        elif pl <= -0.35:
            action = "REDUCE"
            reason = f"{pl*100:.0f}% P&L — near stop, consider reducing size"
        elif pl <= -0.15:
            action = "HOLD"
            reason = f"{pl*100:.0f}% P&L — within normal fluctuation, monitoring"
        else:
            action = "HOLD"
            reason = f"{pl*100:.1f}% P&L — thesis intact"

        return {
            "verdict": "HOLD" if action == "HOLD" else ("EXIT" if action == "EXIT" else "REDUCE"),
            "action": action,
            "confidence": round(max(0.5, 1.0 - abs(pl) * 0.5), 2),
            "thesis_intact": action != "EXIT",
            "invalidation_threatened": pl <= -0.35,
            "reason": reason,
            "source": "mock_post_trade_monitor",
            "model": None,
        }
    except Exception as e:
        from loguru import logger
        logger.warning(f"Mock reassess error: {e}")
        return {"verdict": "UNAVAILABLE", "action": "HOLD", "reason": str(e), "source": "mock_post_trade"}


def is_available() -> bool:
    """Return True if mock LLM is enabled via environment."""
    return os.getenv("MOCK_LLM", "false").lower() == "true"
