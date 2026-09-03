"""
ICT Options Agent — Trading Dashboard

A terminal-style monitoring dashboard for the ICT Options Confluence Agent.
Shows live agent status, AI decisions, options chain evidence, orders and exits.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
import streamlit as st
import pandas as pd
from config import settings

# ── Page config (must be first Streamlit command) ───────────────────────────
st.set_page_config(
    page_title="ICT Options Agent",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS for terminal/trading aesthetic ────────────────────────────────
STYLES = """
<style>
/* ── Reset & Base ───────────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Consolas', monospace;
    background: #0D0F14;
    color: #E6EDF3;
}

/* ── Hide Streamlit chrome ───────────────────────────────────────────────── */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header[data-testid="stHeader"] {background: transparent;}

/* ── Titles ───────────────────────────────────────────────────────────────── */
h1, h2, h3, h4 {
    font-family: 'JetBrains Mono', monospace;
    color: #E6EDF3;
    letter-spacing: -0.02em;
}
h1 { font-size: 1.5rem; font-weight: 600; }
h2 { font-size: 1.1rem; font-weight: 500; color: #8B949E; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 2rem; }
h3 { font-size: 0.9rem; color: #8B949E; }

/* ── Metric Cards ─────────────────────────────────────────────────────────── */
.metric-card {
    background: #161B22;
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 1rem 1.25rem;
    min-width: 140px;
}
.metric-label {
    font-size: 0.7rem;
    color: #8B949E;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 0.25rem;
}
.metric-value {
    font-size: 1.5rem;
    font-weight: 600;
    color: #E6EDF3;
    letter-spacing: -0.02em;
}
.metric-sub {
    font-size: 0.7rem;
    color: #8B949E;
    margin-top: 0.15rem;
}

/* ── Status Indicators ────────────────────────────────────────────────────── */
.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.35rem 0.75rem;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 500;
    letter-spacing: 0.02em;
}
.status-badge::before {
    content: '';
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
}
.status-online { background: #0D1117; border: 1px solid #238636; color: #3FB950; }
.status-online::before { background: #3FB950; box-shadow: 0 0 6px #3FB950; }
.status-halted { background: #0D1117; border: 1px solid #DA3633; color: #FF4444; }
.status-halted::before { background: #FF4444; box-shadow: 0 0 6px #FF4444; animation: pulse 2s infinite; }
.status-wait { background: #0D1117; border: 1px solid #D29922; color: #D29922; }
.status-wait::before { background: #D29922; }

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}

/* ── Decision Cards ───────────────────────────────────────────────────────── */
.decision-card {
    background: #161B22;
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 1rem;
    margin-bottom: 0.75rem;
}
.decision-card.trade { border-left: 3px solid #3FB950; }
.decision-card.wait { border-left: 3px solid #D29922; }
.decision-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.75rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid #21262D;
}
.decision-symbol {
    font-size: 1rem;
    font-weight: 600;
    color: #E6EDF3;
}
.decision-decision {
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    padding: 0.25rem 0.5rem;
    border-radius: 4px;
}
.decision-decision.trade { background: #0D1117; color: #3FB950; border: 1px solid #238636; }
.decision-decision.wait { background: #0D1117; color: #D29922; border: 1px solid #D29922; }

.decision-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 0.75rem;
    margin-bottom: 0.75rem;
}
.decision-item label {
    display: block;
    font-size: 0.65rem;
    color: #8B949E;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.2rem;
}
.decision-item span {
    font-size: 0.85rem;
    color: #E6EDF3;
}

.decision-thesis {
    background: #0D1117;
    border: 1px solid #21262D;
    border-radius: 4px;
    padding: 0.75rem;
    font-size: 0.8rem;
    color: #8B949E;
    line-height: 1.5;
}
.decision-thesis strong { color: #E6EDF3; }

/* ── Tables ───────────────────────────────────────────────────────────────── */
.stDataFrame { border-radius: 6px; overflow: hidden; }
.stDataFrame table { background: #161B22; }
.stDataFrame td, .stDataFrame th {
    border-color: #21262D !important;
    color: #E6EDF3 !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.8rem !important;
}
.stDataFrame th {
    background: #0D1117 !important;
    color: #8B949E !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 0.7rem !important;
}

/* ── Alerts / Info Boxes ──────────────────────────────────────────────────── */
.stAlert {
    background: #161B22 !important;
    border: 1px solid #30363D !important;
    border-radius: 6px !important;
    color: #E6EDF3 !important;
}
.stAlert p { color: #E6EDF3 !important; font-size: 0.85rem; }

/* ── Expanders ────────────────────────────────────────────────────────────── */
.streamlit-expander-header {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.85rem !important;
    color: #8B949E !important;
}
.streamlit-expander-header:hover { color: #E6EDF3 !important; }

/* ── Sidebar ──────────────────────────────────────────────────────────────── */
.css-1d391kg, .css-1lcb5c7 {
    background: #0D0F14 !important;
    border-right: 1px solid #21262D !important;
}
.css-1d391kg h1, .css-1lcb5c7 h1 {
    color: #E6EDF3 !important;
    font-size: 1rem !important;
}

/* ── Buttons ──────────────────────────────────────────────────────────────── */
.stButton button {
    background: #161B22 !important;
    border: 1px solid #30363D !important;
    color: #E6EDF3 !important;
    font-family: 'JetBrains Mono', monospace !important;
    border-radius: 4px !important;
    padding: 0.5rem 1rem !important;
    font-size: 0.8rem !important;
    transition: all 0.2s ease;
}
.stButton button:hover {
    background: #21262D !important;
    border-color: #8B949E !important;
}

/* ── JSON Viewer ──────────────────────────────────────────────────────────── */
pre {
    background: #0D1117 !important;
    border: 1px solid #21262D !important;
    border-radius: 4px !important;
    padding: 0.75rem !important;
    font-size: 0.75rem !important;
    color: #8B949E !important;
    overflow-x: auto;
}

/* ── Scrollbar ────────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #0D0F14; }
::-webkit-scrollbar-thumb { background: #30363D; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #484F58; }
</style>
"""

# Inject CSS
st.markdown(STYLES, unsafe_allow_html=True)


# ── Helper Functions ─────────────────────────────────────────────────────────
def load_audit_files(audit_dir: Path) -> List[Dict[str, Any]]:
    """Load and parse audit cycle files."""
    files = sorted(audit_dir.glob("cycle_*.json"), reverse=True) if audit_dir.exists() else []
    cycles = []
    for f in files[:20]:  # Last 20 cycles
        try:
            with open(f, 'r') as fp:
                data = json.load(fp)
                data['_file'] = f.name
                data['_path'] = str(f)
                cycles.append(data)
        except (json.JSONDecodeError, IOError):
            continue
    return cycles


def format_equity(value: float) -> str:
    """Format equity with dollar sign and commas."""
    if value >= 1000000:
        return f"${value/1000000:.2f}M"
    return f"${value:,.2f}"


def format_pnl(pct: float) -> str:
    """Format P&L percentage with sign and color coding."""
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def get_decision_type(decision: Dict) -> str:
    """Get the decision type (TRADE or WAIT)."""
    d = decision.get("decision", "WAIT").upper()
    return "TRADE" if d == "TRADE" else "WAIT"


def get_ai_decision(signals: List[Dict]) -> Optional[Dict]:
    """Extract the most recent AI decision from signals."""
    for signal in reversed(signals):
        decision = signal.get("ai_decision") or signal.get("veto")
        if decision and decision.get("decision"):
            return decision
    return None


# ── Main App ─────────────────────────────────────────────────────────────────

# Title with terminal aesthetic
st.markdown("""
<div style="display: flex; align-items: center; gap: 1rem; margin-bottom: 2rem;">
    <div style="font-size: 2rem;">📊</div>
    <div>
        <h1 style="margin: 0;">ICT OPTIONS AGENT</h1>
        <div style="font-size: 0.75rem; color: #8B949E; letter-spacing: 0.1em; text-transform: uppercase;">
            Confluence Analysis • AI Reasoning • Options Execution
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# Load audit data
audit_dir = Path(settings.AUDIT_DIR)
cycles = load_audit_files(audit_dir)

if not cycles:
    # Empty state with guidance
    st.markdown("""
    <div style="text-align: center; padding: 4rem 2rem; background: #161B22; border: 1px solid #21262D; border-radius: 8px;">
        <div style="font-size: 3rem; margin-bottom: 1rem;">⚡</div>
        <h2 style="color: #E6EDF3; margin-bottom: 0.5rem;">No cycles yet</h2>
        <p style="color: #8B949E; font-size: 0.9rem; max-width: 500px; margin: 0 auto;">
            Run the agent to generate audit data:<br>
            <code style="background: #0D1117; padding: 0.25rem 0.5rem; border-radius: 4px;">
                python -m src.main --once --mode auto --symbol SPY
            </code>
        </p>
    </div>
    """, unsafe_allow_html=True)
else:
    # ── Latest Cycle ─────────────────────────────────────────────────────
    latest = cycles[0]

    # Status row
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        is_halted = latest.get("halted", False)
        status_class = "status-halted" if is_halted else "status-online"
        status_text = "KILLED" if is_halted else "ONLINE"
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Agent Status</div>
            <div class="status-badge {status_class}">{status_text}</div>
            <div class="metric-sub">Mode: {latest.get('mode', 'auto').upper()}</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        equity = latest.get("equity", 0)
        day_start = latest.get("day_starting_equity", equity)
        pnl_pct = ((equity - day_start) / day_start * 100) if day_start > 0 else 0
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Equity</div>
            <div class="metric-value">{format_equity(equity)}</div>
            <div class="metric-sub" style="color: {'#3FB950' if pnl_pct >= 0 else '#FF4444'}">
                {format_pnl(pnl_pct)} today
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        positions = latest.get("positions_snapshot", [])
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Open Positions</div>
            <div class="metric-value">{len(positions)}</div>
            <div class="metric-sub">Max: {settings.MAX_POSITIONS}</div>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        signals = latest.get("signals", [])
        trades = len([s for s in signals if s.get("ai_decision", {}).get("decision") == "TRADE"])
        waits = len([s for s in signals if s.get("ai_decision", {}).get("decision") == "WAIT"])
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Cycle Activity</div>
            <div class="metric-value" style="font-size: 1.2rem;">{len(signals)} signals</div>
            <div class="metric-sub">
                <span style="color: #3FB950;">{trades} TRADE</span> ·
                <span style="color: #D29922;">{waits} WAIT</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Signals Section ──────────────────────────────────────────────────
    if signals:
        st.markdown("### SIGNAL ANALYSIS")

        for i, signal in enumerate(signals[-10:]):  # Last 10 signals
            decision = signal.get("ai_decision") or signal.get("veto") or {}
            symbol = signal.get("symbol", "UNKNOWN")
            bias = signal.get("bias", "").upper()
            score = signal.get("combined_score", 0)
            time_score = signal.get("time_score", 0)

            dec_type = get_decision_type(decision)
            card_class = "trade" if dec_type == "TRADE" else "wait"

            with st.expander(f"{symbol} · {bias} · Score {score:.2f} · {dec_type}", expanded=False):
                col_a, col_b = st.columns([2, 1])

                with col_a:
                    # Decision details
                    confidence = decision.get("confidence", 0)
                    strategy = decision.get("options_strategy", "NONE")
                    thesis = decision.get("ict_thesis", "")
                    rationale = decision.get("rationale", "")

                    st.markdown(f"""
                    <div class="decision-grid">
                        <div class="decision-item">
                            <label>Decision</label>
                            <span style="color: {'#3FB950' if dec_type == 'TRADE' else '#D29922'}; font-weight: 600;">{dec_type}</span>
                        </div>
                        <div class="decision-item">
                            <label>Structure</label>
                            <span>{strategy}</span>
                        </div>
                        <div class="decision-item">
                            <label>Confidence</label>
                            <span>{confidence:.0%}</span>
                        </div>
                        <div class="decision-item">
                            <label>Time Score</label>
                            <span>{time_score:.2f}</span>
                        </div>
                        <div class="decision-item">
                            <label>Entry Zone</label>
                            <span>${signal.get('entry_zone', 'N/A')}</span>
                        </div>
                        <div class="decision-item">
                            <label>Invalidation</label>
                            <span>${signal.get('stop', 'N/A')}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    if thesis:
                        st.markdown(f"""
                        <div class="decision-thesis">
                            <strong>THESIS:</strong> {thesis}
                        </div>
                        """, unsafe_allow_html=True)

                    if rationale:
                        st.caption(f"**Reasoning:** {rationale}")

                    # Adversarial review
                    review = decision.get("adversarial_review", {})
                    if review:
                        verdict = review.get("verdict", "UNKNOWN")
                        verdict_color = "#3FB950" if verdict == "PASS" else "#FF4444"
                        st.caption(f"**Adversarial Review:** <span style='color: {verdict_color}'>{verdict}</span> — {review.get('reason', '')}", unsafe_allow_html=True)

                with col_b:
                    # Required vs missing confluences
                    required = decision.get("required_confluences", [])
                    missing = decision.get("missing_confluences", [])

                    if required:
                        st.markdown("**Required:**")
                        for r in required:
                            st.caption(f"✓ {r}")

                    if missing:
                        st.markdown("**Missing:**")
                        for m in missing:
                            st.caption(f"✗ {m}")

    # ── Orders & Exits ───────────────────────────────────────────────────
    orders = latest.get("orders", [])
    exits = latest.get("exits", [])

    if orders or exits:
        col_ord, col_ext = st.columns(2)

        with col_ord:
            if orders:
                st.markdown("### ORDERS")
                order_data = []
                for o in orders[-5:]:
                    order_data.append({
                        "Client ID": (o.get("client_order_id") or "")[:16],
                        "Symbol": o.get("symbol", ""),
                        "Strategy": o.get("strategy", ""),
                        "Qty": o.get("qty", ""),
                        "Result": str(o.get("result", ""))[:50],
                    })
                if order_data:
                    df_orders = pd.DataFrame(order_data)
                    st.dataframe(df_orders, use_container_width=True, hide_index=True)

        with col_ext:
            if exits:
                st.markdown("### EXITS")
                exit_data = []
                for e in exits[-5:]:
                    exit_data.append({
                        "Style": e.get("style", ""),
                        "Qty": e.get("qty", ""),
                        "Reason": e.get("reason", ""),
                        "Order": str(e.get("order_id", ""))[:12],
                    })
                if exit_data:
                    df_exits = pd.DataFrame(exit_data)
                    st.dataframe(df_exits, use_container_width=True, hide_index=True)

    # ── Recent Cycles ────────────────────────────────────────────────────
    st.markdown("### RECENT CYCLES")
    cycle_data = []
    for c in cycles[:10]:
        ts = c.get("ts_utc", c.get("_file", ""))
        sig_count = len(c.get("signals", []))
        ord_count = len(c.get("orders", []))
        exit_count = len(c.get("exits", []))
        eq = c.get("equity", 0)
        halted = "H" if c.get("halted") else "-"
        cycle_data.append({
            "Time": ts,
            "Signals": sig_count,
            "Orders": ord_count,
            "Exits": exit_count,
            "Equity": format_equity(eq),
            " Halt": halted,
        })

    if cycle_data:
        df_cycles = pd.DataFrame(cycle_data)
        st.dataframe(df_cycles, use_container_width=True, hide_index=True)

# ── Footer ───────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("""
<div style="display: flex; justify-content: space-between; align-items: center; padding: 1rem 0; font-size: 0.7rem; color: #8B949E;">
    <span>ICT OPTIONS AGENT v1.0</span>
    <span>AI Reasoning • Deterministic Risk • Alpaca Execution</span>
    <span>""" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</span>
</div>
""", unsafe_allow_html=True)
