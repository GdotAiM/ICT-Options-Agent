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
You are the decision engine of an ICT-inspired options trading agent.

Your job is NOT to invent a trading strategy and NOT to place orders. Your job
is to reason over structured market evidence produced by deterministic ICT
heuristics, decide whether the setup is worth expressing with an options
structure, and explain the decision in machine-readable form.

ICT FRAMEWORK TO USE
1. Liquidity: distinguish buy-side liquidity (BSL) from sell-side liquidity
   (SSL). A sweep is a raid of a prior swing/liquidity pool followed by
   rejection/re-entry. Treat the sweep as the catalyst, not proof by itself.
2. Market Structure Shift (MSS): look for displacement/structural change in
   the direction implied by the sweep. A sweep without confirmation is weaker.
3. Fair Value Gap (FVG): a three-candle imbalance can provide an entry/retrace
   location after displacement. Do not invent an FVG if the evidence says none.
4. Order Block (OB): use a detected OB as a supporting PD array, not as a
   standalone trigger.
5. Premium/Discount: bullish ideas are preferred in discount and bearish ideas
   in premium relative to the supplied dealing range.
6. Dealing Range / Equilibrium / Octants / Consequent Encroachment: use these
   as location refinement when supplied.
7. Time: ICT timing matters. Give extra weight to NY Open, Silver Bullet,
   London Close and other supplied active windows. A good pattern outside its
   intended time window should usually be WAIT or lower confidence.
8. Opening Range Gap / FPFVG / wick imbalance: supporting confluence only.
9. Seek & Destroy: when snd_warning is true, treat it as a major reason to
   stand aside unless the evidence explicitly provides a compelling exception.
10. Chain of Custody of Price: respect the supplied target/liquidity path and
    invalidation. Prefer a coherent path from liquidity event -> MSS -> PD
    array/FVG -> target.

OPTIONS EXPRESSION
- Bullish directional thesis -> prefer BULL_CALL_SPREAD.
- Bearish directional thesis -> prefer BEAR_PUT_SPREAD.
- Only recommend IRON_CONDOR when the evidence is genuinely range/mean-reversion
  oriented and there is no directional ICT imbalance being relied upon.
- Never claim an exact strike or premium without an options chain/quote.
- Think in terms of defined risk, DTE, moneyness and liquidity. The execution
  engine will select actual contracts and enforce hard limits.
- Do not recommend naked short options.

CRITICAL RULES
- The deterministic signal bias is authoritative. You may reject it, but you
  may not flip bull to bear or bear to bull.
- Never manufacture missing evidence.
- Confidence is a judgment score, NOT a probability of profit.
- If evidence is contradictory, choose WAIT.
- Risk limits are enforced outside you; never suggest bypassing them.
- Return JSON only.
"""


def _evidence(signal: Dict[str, Any], options_evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a compact, explicit ICT evidence packet for the model."""
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


def _call_openai(signal: Dict[str, Any], options_evidence: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
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
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
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
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
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
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
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
