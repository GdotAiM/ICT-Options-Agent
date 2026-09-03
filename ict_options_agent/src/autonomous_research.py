"""Autonomous hypothesis -> backtest -> OOS -> challenge -> bounded policy engine.

The engine is deliberately conservative: AI may propose and challenge ideas, but
only deterministic statistical gates can promote a bounded policy into production.
"""
from __future__ import annotations
import json, math, os, hashlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger
from src.backtest import run_backtest
from src import state_store

DEFAULT_POLICY = {
    "version": 0,
    "min_combined_score": 0.55,
    "min_time_score": 0.35,
    "require_snd_clear": False,
}

BOUNDS = {
    "min_combined_score": (0.55, 0.95),
    "min_time_score": (0.35, 0.95),
    "require_snd_clear": (False, True),
}

@dataclass
class ExperimentResult:
    hypothesis: Dict[str, Any]
    train: Dict[str, Any]
    oos: Dict[str, Any]
    challenge: Dict[str, Any]
    promotion: Dict[str, Any]
    candidate_policy: Dict[str, Any]


def _policy_path() -> Path:
    configured = os.getenv("RESEARCH_POLICY_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent.parent / "data" / "research_policy.json"


def load_policy() -> Dict[str, Any]:
    path = _policy_path()
    if not path.exists():
        return dict(DEFAULT_POLICY)
    try:
        p = json.loads(path.read_text())
        return _bounded(p)
    except Exception:
        return dict(DEFAULT_POLICY)


def _bounded(policy: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(DEFAULT_POLICY)
    out.update({k: v for k, v in policy.items() if k in BOUNDS})
    lo, hi = BOUNDS["min_combined_score"]
    out["min_combined_score"] = round(min(hi, max(lo, float(out["min_combined_score"]))), 3)
    lo, hi = BOUNDS["min_time_score"]
    out["min_time_score"] = round(min(hi, max(lo, float(out["min_time_score"]))), 3)
    out["require_snd_clear"] = bool(out["require_snd_clear"])
    out["version"] = int(policy.get("version", DEFAULT_POLICY["version"]))
    return out


def save_policy(policy: Dict[str, Any]) -> Dict[str, Any]:
    p = _bounded(policy)
    path = _policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(p, indent=2) + "\n")
    return p


def propose_hypotheses(policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate a small bounded search space; no arbitrary parameter explosion."""
    p = _bounded(policy)
    candidates = []
    for delta in (0.03, 0.06):
        candidates.append({**p, "min_combined_score": min(0.95, p["min_combined_score"] + delta)})
    for delta in (0.03, 0.06):
        candidates.append({**p, "min_time_score": min(0.95, p["min_time_score"] + delta)})
    if not p["require_snd_clear"]:
        candidates.append({**p, "require_snd_clear": True})
    # Deduplicate and cap the experiment budget.
    unique = []
    seen = set()
    for c in candidates:
        c = _bounded(c)
        key = json.dumps(c, sort_keys=True)
        if key not in seen:
            seen.add(key); unique.append(c)
    return unique[:5]


def _split_dates(start: str, end: str, train_ratio: float = 0.65) -> Tuple[str, str, str, str]:
    import pandas as pd
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    cut = s + (e - s) * train_ratio
    # Date strings avoid leakage at the boundary.
    return s.strftime("%Y-%m-%d"), cut.strftime("%Y-%m-%d"), (cut + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")


def _metric(result: Dict[str, Any], key: str, default: float = 0.0) -> float:
    v = result.get(key, default)
    if isinstance(v, str) and v == "inf": return 999.0
    try: return float(v)
    except Exception: return default


def deterministic_challenge(base: Dict[str, Any], candidate: Dict[str, Any], train: Dict[str, Any], oos: Dict[str, Any]) -> Dict[str, Any]:
    """Statistical/adversarial gate independent of the LLM."""
    n = int(oos.get("trades", 0))
    pf = _metric(oos, "profit_factor")
    exp = _metric(oos, "expectancy_r")
    dd = _metric(oos, "max_drawdown_pct", 999)
    base_exp = _metric(base, "expectancy_r")
    base_pf = _metric(base, "profit_factor")
    base_dd = _metric(base, "max_drawdown_pct", 999)
    reasons = []
    if n < 20: reasons.append("insufficient_oos_sample")
    if exp <= 0: reasons.append("non_positive_oos_expectancy")
    if pf < 1.05: reasons.append("weak_oos_profit_factor")
    if dd > max(10.0, base_dd * 1.15): reasons.append("drawdown_not_improved_or_stable")
    if int(train.get("trades", 0)) < 20: reasons.append("insufficient_train_sample")
    train_exp = _metric(train, "expectancy_r")
    if train_exp > 0 and exp < train_exp * 0.45: reasons.append("severe_oos_decay")
    if base_exp > 0 and exp < base_exp * 0.90 and pf <= base_pf: reasons.append("no_clear_edge_over_current_policy")
    return {"pass": not reasons, "reasons": reasons, "sample_oos": n,
            "oos_expectancy_r": exp, "oos_profit_factor": pf, "oos_max_drawdown_pct": dd}


def _llm_challenge(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not key: return None
    try:
        from openai import OpenAI
        base_url = os.getenv("LLM_BASE_URL")
        client = OpenAI(api_key=key, base_url=base_url) if base_url else OpenAI(api_key=key)
        prompt = """Act as an adversarial research reviewer for an ICT trading policy experiment.\n""" \
                """Try to falsify the proposed policy. Look for data leakage, small samples, """ \
                """overfitting, train/OOS decay, and whether the improvement is economically meaningful. """ \
                """Return JSON: {pass: boolean, objections: [string], severity: 'LOW|MEDIUM|HIGH'}."""
        r = client.chat.completions.create(model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            messages=[{"role":"system","content":prompt},{"role":"user","content":json.dumps(payload, default=str)}],
            temperature=0.0, max_tokens=350, response_format={"type":"json_object"})
        return json.loads(r.choices[0].message.content or "{}")
    except Exception as e:
        logger.warning(f"Research challenger unavailable: {e}")
        return None


def run_experiment(symbol: str, start: str, end: str, candidate: Dict[str, Any], base: Optional[Dict[str, Any]] = None) -> ExperimentResult:
    base_policy = load_policy()
    base_policy.update(base or {})
    tr_s, tr_e, oos_s, oos_e = _split_dates(start, end)
    hypothesis = {
        "statement": f"Filtering ICT entries with policy={candidate} improves out-of-sample risk-adjusted expectancy without unacceptable sample loss.",
        "falsifier": "OOS expectancy <= 0, PF < 1.05, severe OOS decay, or insufficient sample.",
        "train_period": [tr_s, tr_e], "oos_period": [oos_s, oos_e],
        "candidate_policy": candidate,
    }
    train = run_backtest(symbol, tr_s, tr_e, policy=candidate)
    oos = run_backtest(symbol, oos_s, oos_e, policy=candidate)
    base_oos = run_backtest(symbol, oos_s, oos_e, policy=base_policy)
    challenge = deterministic_challenge(base_oos, candidate, train, oos)
    llm = _llm_challenge({"hypothesis": hypothesis, "base_oos": base_oos, "candidate_oos": oos, "deterministic_challenge": challenge})
    if llm:
        challenge["llm"] = llm
        if not llm.get("pass", False):
            challenge["pass"] = False
            challenge["reasons"] = list(challenge.get("reasons", [])) + ["llm_adversarial_rejection"]
    promotion = {"eligible": bool(challenge.get("pass")), "action": "PROMOTE" if challenge.get("pass") else "REJECT", "reason": challenge.get("reasons", [])}
    if promotion["eligible"]:
        promoted = dict(candidate); promoted["version"] = int(base_policy.get("version", 0)) + 1
        promotion["policy"] = promoted
    else:
        promotion["policy"] = base_policy
    return ExperimentResult(hypothesis, train, oos, challenge, promotion, candidate)


def run_autonomous_research(symbol: str = "SPY", start: str = "2025-01-01", end: str = "2025-06-30", commit: bool = False) -> Dict[str, Any]:
    current = load_policy()
    candidates = propose_hypotheses(current)
    results = []
    for c in candidates:
        r = run_experiment(symbol, start, end, c, current)
        results.append(asdict(r))
    eligible = [r for r in results if r["promotion"]["eligible"]]
    # Select by OOS expectancy first, then PF, then lower drawdown.
    eligible.sort(key=lambda r: (_metric(r["oos"], "expectancy_r"), _metric(r["oos"], "profit_factor"), -_metric(r["oos"], "max_drawdown_pct")), reverse=True)
    selected = eligible[0] if eligible else None
    committed = current
    if commit and selected:
        committed = save_policy(selected["promotion"]["policy"])
    summary = {"symbol": symbol, "period": [start, end], "current_policy": current,
               "candidate_count": len(candidates), "results": results,
               "selected": selected, "committed_policy": committed if commit else current,
               "commit_requested": commit}
    state_store.record_observation("autonomous_research", {"kind": "experiment_batch", **summary})
    if selected:
        state_store.record_observation("autonomous_research", {"kind": "policy_promotion_candidate", "policy": selected["promotion"]["policy"], "eligible": True, "oos": selected["oos"], "challenge": selected["challenge"]})
    return summary
