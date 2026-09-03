"""Autonomous research loop for the ICT options agent.

The research layer proposes falsifiable hypotheses and observations. It never
gets authority over risk, sizing, contracts, or execution.
"""
from __future__ import annotations
import json, os
from typing import Any, Dict, Optional, List
from loguru import logger
from src import state_store

RESEARCH_SYSTEM_PROMPT = """
You are the autonomous research scientist inside an ICT options trading agent.
Your job is to turn each live setup into a falsifiable hypothesis, identify what
would confirm or invalidate it, and learn from resolved trades. Use ICT language:
liquidity sweep, MSS/displacement, FVG, OB, premium/discount, dealing range,
CE/octants, time windows, Seek & Destroy, and Chain of Custody of Price.
Do not invent evidence. Separate observation from interpretation. Prefer one
clear hypothesis over many vague ones. A hypothesis must be falsifiable.
You may suggest what the agent should observe next, but you cannot override
risk controls or place orders.
Return JSON only.
"""

def _call(prompt: str) -> Optional[Dict[str, Any]]:
    key=os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not key: return None
    try:
        from openai import OpenAI
        base_url=os.getenv("LLM_BASE_URL")
        client=OpenAI(api_key=key, base_url=base_url) if base_url else OpenAI(api_key=key)
        model=os.getenv("LLM_MODEL", "gpt-4o-mini")
        r=client.chat.completions.create(model=model,
          messages=[{"role":"system","content":RESEARCH_SYSTEM_PROMPT},{"role":"user","content":prompt}],
          temperature=0.1,max_tokens=500,response_format={"type":"json_object"})
        d=json.loads(r.choices[0].message.content or "{}")
        d["source"]="openai_research_agent"; d["model"]=model
        return d
    except Exception as e:
        logger.warning(f"Research agent unavailable: {e}"); return None

def build_hypothesis(signal: Dict[str, Any], ai_decision: Dict[str, Any], memory: Optional[List[Dict[str,Any]]]=None) -> Dict[str,Any]:
    prompt=f"""
Create a falsifiable research hypothesis for this candidate trade.
SIGNAL:\n{json.dumps(signal,default=str)}
AI DECISION:\n{json.dumps(ai_decision,default=str)}
RECENT MEMORY:\n{json.dumps(memory or [],default=str)}
Return: {{"hypothesis":"...","confirmation_conditions":["..."],"invalidation_conditions":["..."],"next_observations":["..."],"experiment_tag":"..."}}
"""
    d=_call(prompt)
    if d: return d
    bias=signal.get("bias","neutral")
    return {"hypothesis":f"{bias} ICT thesis remains valid while the liquidity-to-target path and structure remain intact.",
            "confirmation_conditions":["MSS/displacement remains intact","price respects the stated PD/FVG path","target liquidity remains valid"],
            "invalidation_conditions":[f"price reaches/violates {signal.get('stop')}","structure reverses materially","target path is invalidated"],
            "next_observations":["new liquidity sweep","MSS/structure","FVG/PD interaction","option quote quality"],
            "experiment_tag":f"{bias}_ict_options" ,"source":"deterministic_research_fallback"}

def resolve_learning(signal_hash: str, context: Dict[str,Any], position: Dict[str,Any], review: Dict[str,Any]) -> Dict[str,Any]:
    prompt=f"""
Evaluate this completed/updated trade observation as a research experiment.
ORIGINAL CONTEXT:\n{json.dumps(context,default=str)}
CURRENT POSITION:\n{json.dumps(position,default=str)}
AI REVIEW:\n{json.dumps(review,default=str)}
Extract what the market taught us. Do not claim causality from one trade.
Return: {{"outcome":"WIN|LOSS|OPEN|UNKNOWN","evidence_supported":["..."],"evidence_failed":["..."],"lesson":"...","next_hypothesis":"...","confidence":0.0}}
"""
    d=_call(prompt)
    if d: return d
    pl=float(position.get("unrealized_pl",0) or 0)
    return {"outcome":"OPEN","evidence_supported":[],"evidence_failed":[],
            "lesson":"Continue observing; one position is insufficient to establish an edge.",
            "next_hypothesis":context.get("hypothesis",{}).get("hypothesis",""),"confidence":0.2,
            "source":"deterministic_learning_fallback"}
