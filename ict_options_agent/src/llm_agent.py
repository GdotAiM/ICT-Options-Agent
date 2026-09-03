"""
ICT-aware AI trading agent.

The LLM is the reasoning/orchestration layer, not the risk authority. It must
interpret the deterministic ICT evidence, choose WAIT/TRADE and recommend an
options structure. A separate deterministic governor remains authoritative
for risk, sizing, liquidity, options approval and execution.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional
from loguru import logger


SYSTEM_PROMPT = """
You are the decision engine of an ICT RTH Options Agent.

Your job is to reason over a structured RTH (Regular Trading Hours) market
state produced by the RTH session engine, decide whether the current market
delivery warrants an options trade, and explain the decision in
machine-readable form.

RTH FRAMEWORK
The agent operates within US Regular Trading Hours (09:30–16:00 ET) and
interprets market delivery through ICT concepts:

1. SESSION PHASE: AM (09:30–12:00), Lunch (12:00–13:30), PM (13:30–16:00).
   The AM session is primary for new entries. Lunch is lower confidence.
   PM is for continuation or reversal plays.

2. OPENING RANGE GAP (ORG): The gap between prior RTH settlement and the
   09:30 open. Price tends to reprice toward the mid-gap (CE). A gap that
   fills and reverses is a reversal signal. A gap that holds is continuation.

3. OPENING RANGE (09:30–10:00): The first 30 minutes establish the OR.
   Expansion above/below the OR is a directional signal. Rejection at OR
   boundaries is a reversal signal.

4. LIQUIDITY DELIVERY: Overnight highs/lows and OR highs/lows are liquidity
   targets. A sweep (takeout + rejection) is a catalyst. Acceptance (hold
   above/below) is continuation evidence.

5. FIRST PRESENTED FVG: The first Fair Value Gap after the 09:30 open is
   significant — it often provides the entry location for the session's
   primary move.

6. DISPLACEMENT: Strong directional expansion (range > 1.3x average) confirms
   genuine delivery. Without displacement, signals are weaker.

7. PREMIUM/DISCOUNT: Bullish ideas are preferred in discount (below mid-range).
   Bearish ideas are preferred in premium (above mid-range).

8. MSS: Market Structure Shift is ONE piece of structural evidence (5% weight),
   NOT a hard gate. A sweep without MSS is still tradeable if other evidence
   is strong.

THESIS MODELS — classify the current state into one of:
- EXPANSION: Price breaking out of OR with displacement and volume. Directional.
- REVERSAL: Sweep of key liquidity followed by rejection back inside. Directional.
- CONTINUATION: Established AM trend extending into PM. Directional.
- REPRICING: Price filling toward ORG mid-gap or CE. Can be directional or neutral.
- RANGE: No clear delivery. WAIT or IRON_CONDOR if IV supports it.

OPTIONS EXPRESSION
- Bullish directional thesis -> BULL_CALL_SPREAD
- Bearish directional thesis -> BEAR_PUT_SPREAD
- Range/mean-reversion (no directional imbalance) -> IRON_CONDOR
- Conflicting or incomplete evidence -> WAIT
- Never claim an exact strike or premium without an options chain/quote.
- Think in terms of defined risk, DTE, moneyness and liquidity.
- Do not recommend naked short options.

CRITICAL RULES
- The RTH state bias is a hint, not a command. You may reject it.
- Never manufacture missing evidence.
- Confidence is a judgment score, NOT a probability of profit.
- If evidence is contradictory, choose WAIT.
- Risk limits are enforced outside you; never suggest bypassing them.
- Return JSON only.

PAPER TRADING MODE
- When options_chain.available is false or shows zero OI/volume, this is
  expected on a paper trading account — it does NOT mean the market is
  illiquid. Do NOT reject a trade solely because the paper options chain
  lacks real OI/volume data.
- In paper mode, evaluate the thesis on its ICT/RTH merits. The options
  execution layer will handle strike selection deterministically.
- Only reject on options grounds if the chain is genuinely missing (no
  expirations, no strikes at all), not just zero OI.
"""


def _evidence(signal: Dict[str, Any], options_evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a compact ICT evidence packet for the model."""
    keys = [
        "symbol", "bias", "underlying_price", "entry_zone", "stop", "target",
        "sweep_level", "pd_zone", "combined_score", "time_score",
        "active_windows", "time_context", "reason", "snd_warning",
        "snd_profile", "dealing_range", "octant", "consequent_encroachment",
        "body_imbalance", "order_block", "opening_range_gap", "fpfvg",
        "wick_imbalance", "chain_of_custody", "mss", "fvg", "displacement",
    ]
    out = {k: signal.get(k) for k in keys if k in signal}
    if options_evidence is not None:
        out["options_chain"] = options_evidence
    return out


def _rth_evidence(rth_state: Dict[str, Any], options_evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a compact RTH market state packet for the model."""
    keys = [
        "symbol", "session", "timestamp_et", "last_price", "bias",
        "combined_score", "score_breakdown", "rth_open", "prior_rth_close",
        "org", "opening_range", "overnight", "liquidity", "displacement",
        "first_presented_fvg", "mss", "pd_zone", "pd_mid",
        "pd_range_high", "pd_range_low", "or_status", "reason",
        # Micro-bar enrichment fields
        "micro_fvgs", "micro_sweeps", "micro_displacement",
        "micro_fvg_count", "micro_sweep_count", "micro_evidence_bonus",
        "micro_bias", "micro_bias_confirmed",
    ]
    out = {k: rth_state.get(k) for k in keys if k in rth_state}
    if options_evidence is not None:
        out["options_chain"] = options_evidence
    return out


def _fallback(signal: Dict[str, Any], reason: str = "LLM unavailable") -> Dict[str, Any]:
    """Deterministic fallback preserving the exact same agent contract."""
    score = float(signal.get("combined_score", 0.0))
    time_score = float(signal.get("time_score", 0.0))
    snd = bool(signal.get("snd_warning", False))
    bias = signal.get("bias")

    blockers = []
    if score < 0.55:
        blockers.append(f"confluence score {score:.2f} below 0.55")
    if time_score < 0.35:
        blockers.append(f"time score {time_score:.2f} below 0.35")
    if snd:
        blockers.append("Seek & Destroy warning")

    decision = "WAIT" if blockers else "TRADE"
    strategy = "BULL_CALL_SPREAD" if bias == "bull" else "BEAR_PUT_SPREAD"
    if decision == "WAIT":
        rationale = "; ".join(blockers)
    else:
        rationale = "Deterministic ICT evidence supports the directional thesis."

    return {
        "decision": decision,
        "approve": decision == "TRADE",
        "direction": bias,
        "options_strategy": strategy,
        "confidence": max(0.0, min(1.0, score)),
        "ict_thesis": signal.get("reason", ""),
        "required_confluences": ["liquidity sweep", "MSS", "PD location", "time"],
        "missing_confluences": blockers,
        "entry_condition": "Execute only after deterministic quote and risk gates pass.",
        "invalidation": signal.get("stop"),
        "target": signal.get("target"),
        "rationale": rationale,
        "source": "deterministic_fallback",
        "model": None,
        "fallback_reason": reason,
    }


def _make_client():
    """Create an OpenAI-compatible client, honouring LLM_BASE_URL for custom endpoints."""
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY") or "proxy-key"
    base_url = os.getenv("LLM_BASE_URL")
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def _call_openai(signal: Dict[str, Any], options_evidence: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        return None
    try:
        client = _make_client()
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        user_prompt = f"""
Analyze this ICT evidence packet for {signal.get('symbol')}.

{json.dumps(_evidence(signal, options_evidence), default=str, indent=2)}

Return exactly this JSON schema:
{{
  "decision": "TRADE" | "WAIT",
  "approve": true | false,
  "direction": "bull" | "bear" | "neutral",
  "options_strategy": "BULL_CALL_SPREAD" | "BEAR_PUT_SPREAD" | "IRON_CONDOR" | "NONE",
  "confidence": 0.0,
  "ict_thesis": "short market narrative",
  "required_confluences": ["..."],
  "missing_confluences": ["..."],
  "entry_condition": "what must remain true",
  "invalidation": "price/event that invalidates the thesis",
  "target": "liquidity/price objective",
  "rationale": "concise decision explanation",
  "preferred_dte": 7,
  "preferred_moneyness": "ATM_to_slightly_ITM",
  "chain_requirements": ["tight quotes", "adequate open interest"]
}}

Use only supplied evidence. Use the supplied live chain to reason about DTE, moneyness, liquidity and quote quality. Do not invent exact option strikes, premiums or Greeks.
"""
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.05,
            max_tokens=700,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        data["source"] = "openai_ict_agent"
        data["model"] = model
        return data
    except TypeError:
        # Older OpenAI SDKs may not support response_format in the same way.
        try:
            client = _make_client()
            model = os.getenv("LLM_MODEL", "gpt-4o-mini")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(_evidence(signal), default=str)},
                ],
                temperature=0.05,
                max_tokens=700,
            )
            text = response.choices[0].message.content or "{}"
            start, end = text.find("{"), text.rfind("}") + 1
            data = json.loads(text[start:end])
            data["source"] = "openai_ict_agent"
            data["model"] = model
            return data
        except Exception as e:
            logger.warning(f"ICT LLM agent unavailable: {e}")
            return None
    except Exception as e:
        logger.warning(f"ICT LLM agent unavailable: {e}")
        return None


def _challenge_openai(signal: Dict[str, Any], proposal: Dict[str, Any], options_evidence: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Adversarial second-pass reviewer: try to disprove the proposed trade."""
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        return None
    try:
        client = _make_client()
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        prompt = f"""
You are the adversarial ICT thesis challenger. Try to DISPROVE this proposed options trade.
Do not flip the deterministic bias. Check: liquidity sweep quality, MSS/displacement,
FVG/OB/PD location, timing, dealing-range target, Seek & Destroy, Chain of Custody,
and whether the proposed options structure is actually supported by the supplied live chain.
Reject if evidence is missing, contradictory, stale/wide, illiquid, or structurally incoherent.
Return JSON only: {{"verdict":"PASS"|"FAIL","confidence":0.0,"contradictions":["..."],"fatal_risks":["..."],"reason":"..."}}

ICT EVIDENCE:
{json.dumps(_evidence(signal, options_evidence), default=str)}

PROPOSAL:
{json.dumps(proposal, default=str)}
"""
        response = client.chat.completions.create(
            model=model,
            messages=[{"role":"system", "content": SYSTEM_PROMPT}, {"role":"user", "content": prompt}],
            temperature=0.0,
            max_tokens=450,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content or "{}")
        data["source"] = "openai_ict_challenger"
        data["model"] = model
        return data
    except Exception as e:
        logger.warning(f"ICT challenger unavailable: {e}")
        return None


def _validate(data: Dict[str, Any], signal: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize model output and enforce non-negotiable semantic constraints."""
    bias = signal.get("bias")
    decision = str(data.get("decision", "WAIT")).upper()
    direction = str(data.get("direction", bias)).lower()
    strategy = str(data.get("options_strategy", "NONE")).upper()

    if direction not in {"bull", "bear", "neutral"}:
        direction = bias or "neutral"
    if bias in {"bull", "bear"} and direction not in {bias, "neutral"}:
        decision = "WAIT"
        data["rationale"] = "AI direction conflicted with deterministic ICT bias; forced WAIT."
        direction = bias

    if direction == "bull" and strategy not in {"BULL_CALL_SPREAD", "NONE"}:
        decision = "WAIT"
    if direction == "bear" and strategy not in {"BEAR_PUT_SPREAD", "NONE"}:
        decision = "WAIT"

    if strategy == "IRON_CONDOR" and bool(signal.get("snd_warning")):
        decision = "WAIT"
        data["rationale"] = "Seek & Destroy warning blocks an AI-selected condor."

    if decision not in {"TRADE", "WAIT"}:
        decision = "WAIT"
    confidence = float(data.get("confidence", 0.0) or 0.0)
    confidence = max(0.0, min(1.0, confidence))

    data.update({
        "decision": decision,
        "approve": decision == "TRADE",
        "direction": direction,
        "options_strategy": strategy,
        "confidence": confidence,
        "preferred_dte": max(0, min(60, int(float(data.get("preferred_dte", 7) or 7)))),
        "preferred_moneyness": str(data.get("preferred_moneyness", "ATM_to_slightly_ITM")),
        "chain_requirements": data.get("chain_requirements", []),
        "ict_evidence": _evidence(signal),
    })
    return data


def run_ict_agent(signal: Dict[str, Any], require_llm: bool = False, options_evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run primary ICT/options analyst then an adversarial thesis challenge."""
    try:
        llm = _call_openai(signal, options_evidence)
    except TypeError:
        # Compatibility with lightweight test doubles / older adapters.
        llm = _call_openai(signal)
    if llm is None:
        fallback = _fallback(signal)
        if require_llm:
            fallback.update({
                "decision": "WAIT", "approve": False,
                "rationale": "AI_REQUIRED=true but the configured LLM was unavailable; fail-closed.",
                "source": "ai_unavailable_fail_closed",
            })
        return fallback
    validated = _validate(llm, signal)
    validated["ict_evidence"] = _evidence(signal, options_evidence)
    challenge = _challenge_openai(signal, validated, options_evidence)
    if challenge is not None:
        validated["adversarial_review"] = challenge
        if str(challenge.get("verdict", "FAIL")).upper() != "PASS":
            validated["decision"] = "WAIT"
            validated["approve"] = False
            validated["rationale"] = "Adversarial ICT thesis challenge failed: " + str(challenge.get("reason", "contradictory evidence"))
    else:
        # An unavailable challenger is not the same as a passed challenger.
        # Fail closed regardless of require_llm/AI_REQUIRED — a trade must
        # never proceed with zero adversarial review just because the
        # second-pass call happened to error out, time out, or lack a key.
        validated["adversarial_review"] = {"verdict": "UNAVAILABLE"}
        validated["decision"] = "WAIT"
        validated["approve"] = False
        validated["rationale"] = "Adversarial ICT thesis review unavailable; fail closed."
    return validated


# ── RTH Agent ───────────────────────────────────────────────────

def _call_rth_openai(rth_state: Dict[str, Any], options_evidence: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Call the LLM with an RTH market state packet."""
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        return None
    try:
        client = _make_client()
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        user_prompt = f"""
Analyze this RTH market state for {rth_state.get('symbol')}.

{json.dumps(_rth_evidence(rth_state, options_evidence), default=str, indent=2)}

The state may include micro_bar evidence (micro_fvgs, micro_sweeps, micro_displacement)
from 15-second bars built out of trade data. These are higher-density patterns that
confirm or contradict the 1m/5m evidence. Weight them as confirming signals.

If options_chain.available is false, this is a PAPER TRADING account — do not
reject solely for missing options OI/volume. Evaluate on ICT/RTH merits.

Classify the current market delivery model (EXPANSION / REVERSAL / CONTINUATION / REPRICING / RANGE)
and decide whether to TRADE or WAIT.

Return exactly this JSON schema:
{{
  "decision": "TRADE" | "WAIT",
  "approve": true | false,
  "direction": "bull" | "bear" | "neutral",
  "thesis_model": "EXPANSION" | "REVERSAL" | "CONTINUATION" | "REPRICING" | "RANGE",
  "options_strategy": "BULL_CALL_SPREAD" | "BEAR_PUT_SPREAD" | "IRON_CONDOR" | "NONE",
  "confidence": 0.0,
  "ict_thesis": "short market narrative grounded in the RTH state",
  "required_confluences": ["..."],
  "missing_confluences": ["..."],
  "entry_condition": "what must remain true",
  "invalidation": "price/event that invalidates the thesis",
  "target": "liquidity/price objective",
  "rationale": "concise decision explanation",
  "preferred_dte": 7,
  "preferred_moneyness": "ATM_to_slightly_ITM",
  "chain_requirements": ["tight quotes", "adequate open interest"]
}}

Use only supplied evidence. Do not invent exact option strikes, premiums or Greeks.
"""
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.05,
            max_tokens=700,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        data = _safe_json_parse(raw)
        if data is None:
            logger.warning(f"RTH agent returned unparseable JSON: {raw[:100]}")
            return None
        data["source"] = "openai_rth_agent"
        data["model"] = model
        return data
    except Exception as e:
        logger.warning(f"RTH LLM agent unavailable: {e}")
        return None


def _rth_fallback(rth_state: Dict[str, Any], reason: str = "LLM unavailable") -> Dict[str, Any]:
    """Deterministic fallback for the RTH agent."""
    score = float(rth_state.get("combined_score", 0.0))
    bias = rth_state.get("bias", "neutral")
    session = rth_state.get("session", "")

    blockers = []
    if score < 0.35:
        blockers.append(f"RTH score {score:.2f} below 0.35")
    if session == "rth_lunch":
        blockers.append("lunch session — lower confidence")
    if bias == "neutral":
        blockers.append("no directional bias from RTH evidence")

    decision = "WAIT" if blockers else "TRADE"
    strategy = "BULL_CALL_SPREAD" if bias == "bull" else "BEAR_PUT_SPREAD" if bias == "bear" else "NONE"
    if decision == "WAIT":
        rationale = "; ".join(blockers)
    else:
        rationale = "RTH evidence supports the directional thesis."

    return {
        "decision": decision,
        "approve": decision == "TRADE",
        "direction": bias,
        "thesis_model": "RANGE",
        "options_strategy": strategy,
        "confidence": max(0.0, min(1.0, score)),
        "ict_thesis": rth_state.get("reason", ""),
        "required_confluences": ["RTH session", "liquidity", "ORG", "displacement"],
        "missing_confluences": blockers,
        "entry_condition": "Execute only after deterministic quote and risk gates pass.",
        "invalidation": None,
        "target": None,
        "rationale": rationale,
        "source": "deterministic_fallback",
        "model": None,
        "fallback_reason": reason,
    }


def _validate_rth(data: Dict[str, Any], rth_state: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize RTH model output."""
    bias = rth_state.get("bias", "neutral")
    decision = str(data.get("decision", "WAIT")).upper()
    direction = str(data.get("direction", bias)).lower()
    strategy = str(data.get("options_strategy", "NONE")).upper()

    if direction not in {"bull", "bear", "neutral"}:
        direction = bias or "neutral"

    # Allow the AI to go neutral (unlike old agent which forced bias match)
    if direction == "bull" and strategy not in {"BULL_CALL_SPREAD", "NONE"}:
        decision = "WAIT"
    if direction == "bear" and strategy not in {"BEAR_PUT_SPREAD", "NONE"}:
        decision = "WAIT"

    if decision not in {"TRADE", "WAIT"}:
        decision = "WAIT"
    confidence = float(data.get("confidence", 0.0) or 0.0)
    confidence = max(0.0, min(1.0, confidence))

    data.update({
        "decision": decision,
        "approve": decision == "TRADE",
        "direction": direction,
        "options_strategy": strategy,
        "confidence": confidence,
        "preferred_dte": max(0, min(60, int(float(data.get("preferred_dte", 7) or 7)))),
        "preferred_moneyness": str(data.get("preferred_moneyness", "ATM_to_slightly_ITM")),
        "chain_requirements": data.get("chain_requirements", []),
        "rth_evidence": _rth_evidence(rth_state),
    })
    return data


def run_rth_agent(
    rth_state: Dict[str, Any],
    require_llm: bool = False,
    options_evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the RTH-aware AI thesis agent with adversarial challenge."""
    llm = _call_rth_openai(rth_state, options_evidence)
    if llm is None:
        fallback = _rth_fallback(rth_state)
        if require_llm:
            fallback.update({
                "decision": "WAIT", "approve": False,
                "rationale": "AI_REQUIRED=true but the configured LLM was unavailable; fail-closed.",
                "source": "ai_unavailable_fail_closed",
            })
        return fallback

    validated = _validate_rth(llm, rth_state)
    validated["rth_evidence"] = _rth_evidence(rth_state, options_evidence)

    # Adversarial challenge
    challenge = _challenge_rth_openai(rth_state, validated, options_evidence)
    if challenge is not None:
        validated["adversarial_review"] = challenge
        if str(challenge.get("verdict", "FAIL")).upper() != "PASS":
            validated["decision"] = "WAIT"
            validated["approve"] = False
            validated["rationale"] = "Adversarial RTH thesis challenge failed: " + str(challenge.get("reason", "contradictory evidence"))
    else:
        validated["adversarial_review"] = {"verdict": "UNAVAILABLE"}
        validated["decision"] = "WAIT"
        validated["approve"] = False
        validated["rationale"] = "Adversarial RTH thesis review unavailable; fail closed."
    return validated


def _safe_json_parse(text: str) -> Optional[Dict[str, Any]]:
    """Parse JSON tolerantly, handling common LLM output issues."""
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting JSON from text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
    # Try fixing trailing commas
    import re
    cleaned = re.sub(r",\s*}", "}", text[start:end] if start >= 0 else text)
    cleaned = re.sub(r",\s*]", "]", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    return None


def _challenge_rth_openai(
    rth_state: Dict[str, Any],
    proposal: Dict[str, Any],
    options_evidence: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Adversarial reviewer for RTH thesis."""
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        return None
    try:
        client = _make_client()
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        prompt = f"""
You are the adversarial RTH thesis challenger. Try to DISPROVE this proposed options trade.
Check: session phase appropriateness, ORG quality, opening range behavior, liquidity sweep validity,
displacement strength, FVG relevance, PD location, and whether the proposed options structure
is supported by the supplied live chain.

PAPER TRADING MODE: If options_chain.available is false or shows zero OI/volume, this is
expected on a paper account. Do NOT reject solely for options chain illiquidity — evaluate
the thesis on its ICT/RTH structural merits. Only reject on options grounds if the chain
is genuinely missing (no expirations at all).

Reject if ICT/RTH evidence is missing, contradictory, or structurally incoherent.
Return JSON only: {{"verdict":"PASS"|"FAIL","confidence":0.0,"contradictions":["..."],"fatal_risks":["..."],"reason":"..."}}

RTH STATE:
{json.dumps(_rth_evidence(rth_state, options_evidence), default=str)}

PROPOSAL:
{json.dumps(proposal, default=str)}
"""
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=450,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        data = _safe_json_parse(raw)
        if data is None:
            logger.warning(f"RTH challenger returned unparseable JSON: {raw[:100]}")
            return None
        data["source"] = "openai_rth_challenger"
        data["model"] = model
        return data
    except Exception as e:
        logger.warning(f"RTH challenger unavailable: {e}")
        return None


def reassess_open_position(context: Dict[str, Any], position: Dict[str, Any], require_llm: bool = False) -> Dict[str, Any]:
    """AI post-trade monitor: reassess the original ICT thesis against live position state.

    HOLD is the safe default action whenever the monitor can't run — deterministic
    exits (stop/target/DTE) remain authoritative regardless of this verdict, so
    HOLD never bypasses a risk control. The verdict is always reported as
    UNAVAILABLE in that case (not conditionally on require_llm) so the audit
    trail consistently distinguishes "monitor ran and said hold" from
    "monitor didn't run at all", the same way it does for a caught exception.
    """
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        return {"verdict": "UNAVAILABLE", "action": "HOLD", "reason": "LLM unavailable"}
    try:
        client = _make_client()
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        prompt = f"""
You are the post-trade ICT position monitor. Reassess the original thesis using current position state.
Check whether the liquidity target remains valid, MSS/structure remains intact, price is still in the
expected PD path, invalidation is threatened, and whether the option position's current P/L warrants
HOLD, EXIT, or REDUCE. Do not override deterministic risk controls. If risk data is missing, choose HOLD.
Return JSON only: {{"verdict":"HOLD"|"EXIT"|"REDUCE","action":"HOLD"|"EXIT"|"REDUCE","confidence":0.0,"thesis_intact":true,"invalidation_threatened":false,"reason":"..."}}

ORIGINAL CONTEXT:
{json.dumps(context, default=str)}
CURRENT POSITION:
{json.dumps(position, default=str)}
"""
        response = client.chat.completions.create(
            model=model,
            messages=[{"role":"system", "content": SYSTEM_PROMPT}, {"role":"user", "content": prompt}],
            temperature=0.0, max_tokens=300, response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content or "{}")
        data["source"] = "openai_post_trade_monitor"
        data["model"] = model
        return data
    except Exception as e:
        logger.warning(f"Post-trade AI monitor unavailable: {e}")
        return {"verdict": "UNAVAILABLE", "action": "HOLD", "reason": str(e)}


# Backwards-compatible name for callers that used the old reviewer.
def review_signal(signal: Dict[str, Any]) -> Dict[str, Any]:
    return run_ict_agent(signal)
