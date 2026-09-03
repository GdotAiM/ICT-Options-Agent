"""
Minimal Streamlit status dashboard for the ICT Options Agent.

Run:  streamlit run streamlit_app.py
Shows equity, kill-switch, open positions (from latest audit or live if keys set),
and recent cycle decision trails.
"""
from __future__ import annotations
import json
from pathlib import Path
import streamlit as st
from config import settings

st.set_page_config(page_title="ICT Options Agent", layout="wide")
st.title("ICT Options Agent — Status")

audit_dir = Path(settings.AUDIT_DIR)
files = sorted(audit_dir.glob("cycle_*.json"), reverse=True) if audit_dir.exists() else []

col1, col2, col3 = st.columns(3)

latest = None
if files:
    try:
        latest = json.loads(files[0].read_text())
    except Exception as e:
        st.error(f"Failed to read audit: {e}")

if latest:
    col1.metric("Equity", f"${latest.get('equity', 0):,.2f}")
    col2.metric("Options level", latest.get("options_level", "?"))
    col3.metric("Kill switch", "ON" if latest.get("halted") else "off")
    st.caption(f"Last cycle: {latest.get('ts_utc')} | mode={latest.get('mode')}")

    st.subheader("Positions (snapshot)")
    positions = latest.get("positions") or []
    if positions:
        st.dataframe(positions, use_container_width=True)
    else:
        st.info("No open positions in latest snapshot.")

    st.subheader("AI decisions & signals")
    for s in latest.get("signals") or []:
        veto = s.get("ai_decision") or s.get("veto") or {}
        with st.expander(
            f"{s.get('symbol')} {s.get('bias')} score={s.get('combined_score')} "
            f"| approve={veto.get('approve')}"
        ):
            c1, c2, c3 = st.columns(3)
            c1.metric("AI decision", veto.get("decision", "WAIT"))
            c2.metric("Options expression", veto.get("options_strategy", "NONE"))
            c3.metric("AI confidence", f"{float(veto.get('confidence', 0)):.0%}")
            st.write("**ICT thesis:**", veto.get("ict_thesis", ""))
            st.write("**Required confluences:**", ", ".join(veto.get("required_confluences", [])))
            st.write("**Missing / blockers:**", ", ".join(veto.get("missing_confluences", [])) or "None")
            st.write("**Entry condition:**", veto.get("entry_condition", ""))
            st.write("**Invalidation:**", veto.get("invalidation", ""))
            st.write("**Target:**", veto.get("target", ""))
            st.write("**Preferred DTE:**", veto.get("preferred_dte", ""))
            st.write("**Moneyness:**", veto.get("preferred_moneyness", ""))
            review = veto.get("adversarial_review") or {}
            if review:
                st.write("**Adversarial review:**", review.get("verdict", "UNKNOWN"), "—", review.get("reason", ""))
            chain = s.get("options_chain_evidence") or {}
            if chain:
                with st.expander("Live options-chain evidence"):
                    st.json(chain)
            st.json(s)

    st.subheader("AI post-trade feedback")
    reassess = [s for s in (latest.get("signals") or []) if s.get("type") == "ai_post_trade_reassessment"]
    st.json(reassess or [])

    st.subheader("Orders / exits")
    c1, c2 = st.columns(2)
    with c1:
        st.write("Orders")
        st.json(latest.get("orders") or [])
    with c2:
        st.write("Exits")
        st.json(latest.get("exits") or [])
else:
    st.warning("No audit cycles yet. Run the agent once to generate logs/audit/cycle_*.json")

st.subheader("Recent cycles")
for f in files[:15]:
    st.text(f.name)
