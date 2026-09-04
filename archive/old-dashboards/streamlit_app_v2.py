"""
ICT Options Agent — Trading Dashboard v2
A premium terminal-style monitoring dashboard.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import streamlit as st
import pandas as pd
from config import settings

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ICT Options Agent",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Premium CSS ────────────────────────────────────────────────────────────────
STYLES = """
<style>
/* ── Base ───────────────────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Consolas', monospace;
    background: #08090C;
    color: #E2E8F0;
}

/* ── Hide Streamlit chrome ────────────────────────────────────────────────── */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header[data-testid="stHeader"] {background: transparent; padding: 0;}
[data-testid="stSidebar"] {background: #0D1117 !important; border-right: 1px solid #21262D !important;}

/* ── Hero Section ─────────────────────────────────────────────────────────── */
.hero {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1.5rem 0 2rem;
    border-bottom: 1px solid #21262D;
    margin-bottom: 1.5rem;
}
.hero-left h1 {
    margin: 0;
    font-size: 1.75rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #F6F8FA;
}
.hero-left .subtitle {
    font-size: 0.7rem;
    color: #8B949E;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-top: 0.25rem;
}
.hero-right {
    text-align: right;
    font-size: 0.7rem;
    color: #8B949E;
}
.hero-right .clock {
    font-size: 1.1rem;
    color: #F6F8FA;
    font-weight: 600;
}

/* ── Metric Cards ─────────────────────────────────────────────────────────── */
.metrics-row {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1rem;
    margin-bottom: 1.5rem;
}
.metric-card {
    background: linear-gradient(135deg, #161B22 0%, #0D1117 100%);
    border: 1px solid #30363D;
    border-radius: 10px;
    padding: 1.25rem 1.5rem;
    position: relative;
    overflow: hidden;
}
.metric-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    border-radius: 10px 10px 0 0;
}
.metric-card.status::before { background: linear-gradient(90deg, #3FB950, #238636); }
.metric-card.equity::before { background: linear-gradient(90deg, #58A6FF, #1F6FEB); }
.metric-card.positions::before { background: linear-gradient(90deg, #D29922, #BB8009); }
.metric-card.activity::before { background: linear-gradient(90deg, #BC8Cff, #8957e5); }

.metric-label {
    font-size: 0.65rem;
    color: #8B949E;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 0.5rem;
}
.metric-value {
    font-size: 1.65rem;
    font-weight: 700;
    color: #F6F8FA;
    letter-spacing: -0.02em;
    line-height: 1.2;
}
.metric-sub {
    font-size: 0.7rem;
    color: #8B949E;
    margin-top: 0.35rem;
}
.pnl-positive { color: #3FB950 !important; }
.pnl-negative { color: #FF4444 !important; }

/* ── Status Badge ─────────────────────────────────────────────────────────── */
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.4rem 0.9rem;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.05em;
}
.status-pill.online {
    background: rgba(63, 185, 80, 0.1);
    border: 1px solid rgba(63, 185, 80, 0.4);
    color: #3FB950;
}
.status-pill.halted {
    background: rgba(255, 68, 68, 0.1);
    border: 1px solid rgba(255, 68, 68, 0.4);
    color: #FF4444;
}
.status-dot {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: currentColor;
    animation: blink 2s infinite;
}
@keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
}

/* ── Section Headers ──────────────────────────────────────────────────────── */
.section-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin: 2rem 0 1rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid #21262D;
}
.section-header h2 {
    margin: 0;
    font-size: 0.8rem;
    font-weight: 600;
    color: #8B949E;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}
.section-count {
    background: #21262D;
    border: 1px solid #30363D;
    border-radius: 10px;
    padding: 0.15rem 0.5rem;
    font-size: 0.65rem;
    color: #8B949E;
}

/* ── Position Cards ───────────────────────────────────────────────────────── */
.positions-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 0.75rem;
    margin-bottom: 1.5rem;
}
.position-card {
    background: #161B22;
    border: 1px solid #30363D;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.position-card.profit { border-left: 3px solid #3FB950; }
.position-card.loss { border-left: 3px solid #FF4444; }
.position-card.neutral { border-left: 3px solid #30363D; }

.pos-symbol {
    font-size: 0.85rem;
    font-weight: 600;
    color: #F6F8FA;
}
.pos-detail {
    font-size: 0.65rem;
    color: #8B949E;
    margin-top: 0.2rem;
}
.pos-pnl {
    text-align: right;
}
.pos-pnl-value {
    font-size: 1.1rem;
    font-weight: 700;
}
.pos-pnl-label {
    font-size: 0.6rem;
    color: #8B949E;
    text-transform: uppercase;
}

/* ── Signal Cards ─────────────────────────────────────────────────────────── */
.signal-card {
    background: #161B22;
    border: 1px solid #30363D;
    border-radius: 8px;
    margin-bottom: 0.75rem;
    overflow: hidden;
}
.signal-card.trade { border-left: 3px solid #3FB950; }
.signal-card.wait { border-left: 3px solid #D29922; }

.signal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 1.25rem;
    cursor: pointer;
}
.signal-header:hover { background: #1C2128; }
.signal-symbol {
    font-size: 1rem;
    font-weight: 700;
    color: #F6F8FA;
}
.signal-meta {
    display: flex;
    gap: 1rem;
    align-items: center;
}
.signal-badge {
    padding: 0.2rem 0.6rem;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.signal-badge.trade {
    background: rgba(63, 185, 80, 0.15);
    color: #3FB950;
    border: 1px solid rgba(63, 185, 80, 0.3);
}
.signal-badge.wait {
    background: rgba(210, 153, 34, 0.15);
    color: #D29922;
    border: 1px solid rgba(210, 153, 34, 0.3);
}
.signal-score {
    font-size: 0.8rem;
    color: #8B949E;
}

.signal-body {
    padding: 0 1.25rem 1rem;
    border-top: 1px solid #21262D;
    padding-top: 1rem;
}
.signal-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1rem;
    margin-bottom: 1rem;
}
.sig-item label {
    display: block;
    font-size: 0.6rem;
    color: #8B949E;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 0.25rem;
}
.sig-item span {
    font-size: 0.85rem;
    color: #E2E8F0;
}
.signal-thesis {
    background: #0D1117;
    border: 1px solid #21262D;
    border-radius: 6px;
    padding: 0.75rem 1rem;
    font-size: 0.78rem;
    color: #8B949E;
    line-height: 1.6;
}
.signal-thesis strong { color: #E2E8F0; }

/* ── Tables ───────────────────────────────────────────────────────────────── */
.stDataFrame { border-radius: 8px; overflow: hidden; }
.stDataFrame table { background: #161B22; }
.stDataFrame td, .stDataFrame th {
    border-color: #21262D !important;
    color: #E2E8F0 !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem !important;
    padding: 0.75rem 1rem !important;
}
.stDataFrame th {
    background: #0D1117 !important;
    color: #8B949E !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.68rem !important;
    font-weight: 600 !important;
}

/* ── Empty State ──────────────────────────────────────────────────────────── */
.empty-state {
    text-align: center;
    padding: 4rem 2rem;
    background: #161B22;
    border: 1px dashed #30363D;
    border-radius: 12px;
    margin: 2rem 0;
}
.empty-icon { font-size: 3rem; margin-bottom: 1rem; }
.empty-title {
    font-size: 1.1rem;
    font-weight: 600;
    color: #E2E8F0;
    margin-bottom: 0.5rem;
}
.empty-desc {
    font-size: 0.8rem;
    color: #8B949E;
    max-width: 400px;
    margin: 0 auto;
    line-height: 1.6;
}

/* ── Footer ───────────────────────────────────────────────────────────────── */
.footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1.5rem 0;
    border-top: 1px solid #21262D;
    margin-top: 2rem;
    font-size: 0.68rem;
    color: #484F58;
}
.footer span { color: #8B949E; }

/* ── Scrollbar ────────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #0D0F14; }
::-webkit-scrollbar-thumb { background: #30363D; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #484F58; }

/* ── Expander ─────────────────────────────────────────────────────────────── */
.streamlit-expander-header {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.85rem !important;
    color: #8B949E !important;
    padding: 0.75rem 1rem !important;
}
.streamlit-expander-header:hover { color: #E2E8F0 !important; }

/* ── Column spacer fix ────────────────────────────────────────────────────── */
div[data-testid="stColumn"] > div { padding: 0 !important; }
</style>
"""

st.markdown(STYLES, unsafe_allow_html=True)

# ── Helpers ────────────────────────────────────────────────────────────────────

def load_audit_files(audit_dir: Path) -> List[Dict[str, Any]]:
    files = sorted(audit_dir.glob("cycle_*.json"), reverse=True) if audit_dir.exists() else []
    cycles = []
    for f in files[:30]:
        try:
            with open(f, 'r') as fp:
                data = json.load(fp)
                data['_file'] = f.name
                cycles.append(data)
        except (json.JSONDecodeError, IOError):
            continue
    return cycles


def format_equity(value: float) -> str:
    if value >= 1000000:
        return f"${value/1000000:.2f}M"
    return f"${value:,.2f}"


def format_pnl(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def now_et_str() -> str:
    import pytz
    et = pytz.timezone("US/Eastern")
    return datetime.now(et).strftime("%Y-%m-%d  %H:%M:%S ET")


# ── Load Data ──────────────────────────────────────────────────────────────────

audit_dir = Path(settings.AUDIT_DIR)
cycles = load_audit_files(audit_dir)

# ── Hero ───────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="hero">
    <div class="hero-left">
        <h1>📊 ICT OPTIONS AGENT</h1>
        <div class="subtitle">Confluence Analysis &nbsp;•&nbsp; AI Reasoning &nbsp;•&nbsp; Options Execution</div>
    </div>
    <div class="hero-right">
        <div class="clock">{now_et_str()}</div>
        <div>Market: {"OPEN" if 9 <= datetime.now(pytz.timezone("US/Eastern")).hour < 16 else "PRE-MARKET"}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── No Data State ──────────────────────────────────────────────────────────────
if not cycles:
    st.markdown("""
    <div class="empty-state">
        <div class="empty-icon">⚡</div>
        <div class="empty-title">No cycles recorded yet</div>
        <div class="empty-desc">
            Run the agent to begin trading:<br>
            <code style="background:#0D1117;padding:0.35rem 0.75rem;border-radius:4px;display:inline-block;margin-top:0.75rem;font-size:0.75rem;">
                cd ict_options_agent &amp;&amp; PYTHONPATH=. python src/main.py --loop
            </code>
        </div>
    </div>
    """, unsafe_allow_html=True)
else:
    latest = cycles[0]

    # ── Metrics Row ──────────────────────────────────────────────────────
    equity = latest.get("equity", 0)
    day_start = latest.get("day_starting_equity", equity)
    pnl_pct = ((equity - day_start) / day_start * 100) if day_start > 0 else 0
    is_halted = latest.get("halted", False)
    positions = latest.get("positions_snapshot", [])
    signals = latest.get("signals", [])
    orders = latest.get("orders", [])
    exits = latest.get("exits", [])
    trades_today = len([s for s in signals if s.get("ai_decision", {}).get("decision") == "TRADE"])
    waits_today = len([s for s in signals if s.get("ai_decision", {}).get("decision") == "WAIT"])

    st.markdown(f"""
    <div class="metrics-row">
        <div class="metric-card status">
            <div class="metric-label">Agent Status</div>
            <div class="metric-value">
                <span class="status-pill {'online' if not is_halted else 'halted'}">
                    <span class="status-dot"></span>
                    {'ONLINE' if not is_halted else 'KILLED'}
                </span>
            </div>
            <div class="metric-sub">Mode: {latest.get('mode', 'auto').upper()}</div>
        </div>
        <div class="metric-card equity">
            <div class="metric-label">Account Equity</div>
            <div class="metric-value">{format_equity(equity)}</div>
            <div class="metric-sub {'pnl-positive' if pnl_pct >= 0 else 'pnl-negative'}">
                {format_pnl(pnl_pct)} today
            </div>
        </div>
        <div class="metric-card positions">
            <div class="metric-label">Open Positions</div>
            <div class="metric-value">{len(positions)}</div>
            <div class="metric-sub">Max: {settings.MAX_POSITIONS} &nbsp;|&nbsp; Level: {latest.get('options_level', '?')}</div>
        </div>
        <div class="metric-card activity">
            <div class="metric-label">Cycle Activity</div>
            <div class="metric-value" style="font-size:1.3rem;">{len(signals)} signals</div>
            <div class="metric-sub">
                <span style="color:#3FB950;">{trades_today} TRADE</span>
                &nbsp;·&nbsp;
                <span style="color:#D29922;">{waits_today} WAIT</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Positions Section ────────────────────────────────────────────────
    if positions:
        st.markdown('<div class="section-header"><h2>Open Positions</h2><span class="section-count">' + str(len(positions)) + '</span></div>', unsafe_allow_html=True)
        st.markdown('<div class="positions-grid">', unsafe_allow_html=True)
        for pos in positions:
            sym = pos.get("symbol", "?")
            qty = pos.get("qty", "0")
            plpc = float(pos.get("unrealized_plpc") or 0)
            mkt_val = pos.get("market_value", 0)
            side = pos.get("side", "")

            pnl_class = "profit" if plpc > 0 else "loss" if plpc < 0 else "neutral"
            pnl_color = "#3FB950" if plpc > 0 else "#FF4444" if plpc < 0 else "#8B949E"
            pnl_str = f"{plpc:+.1%}"

            # Parse option symbol for cleaner display
            try:
                parts = sym
                underlying = parts[:3]
                exp = parts[3:11]
                strike = float(parts[11:]) / 1000
                clean_sym = f"{underlying} {exp} ${strike:.0f}"
            except Exception:
                clean_sym = sym

            st.markdown(f"""
            <div class="position-card {pnl_class}">
                <div>
                    <div class="pos-symbol">{clean_sym}</div>
                    <div class="pos-detail">qty={qty} &nbsp;·&nbsp; {side.replace('PositionSide.','')} &nbsp;·&nbsp; MV=${float(mkt_val or 0):,.0f}</div>
                </div>
                <div class="pos-pnl">
                    <div class="pos-pnl-value" style="color:{pnl_color}">{pnl_str}</div>
                    <div class="pos-pnl-label">Unrealized P&L</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Signals Section ──────────────────────────────────────────────────
    if signals:
        st.markdown('<div class="section-header"><h2>AI Signal History</h2><span class="section-count">' + str(len(signals)) + '</span></div>', unsafe_allow_html=True)

        for sig in signals[-15:]:
            decision = sig.get("ai_decision") or sig.get("veto") or {}
            symbol = sig.get("symbol", "UNKNOWN")
            bias = sig.get("bias", "neutral").upper()
            score = sig.get("combined_score", 0)
            time_score = sig.get("time_score", 0)
            dec_type = "TRADE" if decision.get("decision") == "TRADE" else "WAIT"
            card_class = "trade" if dec_type == "TRADE" else "wait"

            confidence = decision.get("confidence", 0)
            strategy = decision.get("options_strategy", "NONE")
            thesis = decision.get("ict_thesis", "")
            rationale = decision.get("rationale", "")
            review = decision.get("adversarial_review", {})
            verdict = review.get("verdict", "UNAVAILABLE")
            verdict_color = "#3FB950" if verdict == "PASS" else "#FF4444" if verdict == "FAIL" else "#8B949E"

            st.markdown(f"""
            <div class="signal-card {card_class}">
                <div class="signal-header">
                    <div>
                        <span class="signal-symbol">{symbol}</span>
                        <span style="color:#8B949E; font-size:0.8rem; margin-left:0.5rem;">{bias}</span>
                    </div>
                    <div class="signal-meta">
                        <span class="signal-score">score {score:.2f} &nbsp;·&nbsp; time {time_score:.2f}</span>
                        <span class="signal-badge {dec_type.lower()}">{dec_type}</span>
                    </div>
                </div>
                <div class="signal-body">
                    <div class="signal-grid">
                        <div class="sig-item"><label>Strategy</label><span>{strategy}</span></div>
                        <div class="sig-item"><label>Confidence</label><span>{confidence:.0%}</span></div>
                        <div class="sig-item"><label>Adversarial</label><span style="color:{verdict_color}">{verdict}</span></div>
                    </div>
                    {"<div class='signal-thesis'><strong>THESIS:</strong> " + thesis + "</div>" if thesis else ""}
                </div>
            </div>
            """, unsafe_allow_html=True)

    # ── Orders & Exits ───────────────────────────────────────────────────
    if orders or exits:
        col_ord, col_ext = st.columns(2)

        with col_ord:
            if orders:
                st.markdown('<div class="section-header"><h2>Recent Orders</h2><span class="section-count">' + str(len(orders)) + '</span></div>', unsafe_allow_html=True)
                order_rows = []
                for o in orders[-10:]:
                    order_rows.append({
                        "Client ID": (o.get("client_order_id") or "—")[:12],
                        "Symbol": o.get("symbol", ""),
                        "Strategy": o.get("strategy", ""),
                        "Qty": o.get("qty", ""),
                        "Result": str(o.get("result", ""))[:40],
                    })
                df_orders = pd.DataFrame(order_rows)
                st.dataframe(df_orders, use_container_width=True, hide_index=True)

        with col_ext:
            if exits:
                st.markdown('<div class="section-header"><h2>Exits</h2><span class="section-count">' + str(len(exits)) + '</span></div>', unsafe_allow_html=True)
                exit_rows = []
                for e in exits[-10:]:
                    exit_rows.append({
                        "Style": e.get("style", ""),
                        "Qty": e.get("qty", ""),
                        "Reason": e.get("reason", ""),
                        "Order": str(e.get("order_id", ""))[:10],
                    })
                df_exits = pd.DataFrame(exit_rows)
                st.dataframe(df_exits, use_container_width=True, hide_index=True)

    # ── Cycle History ────────────────────────────────────────────────────
    st.markdown('<div class="section-header"><h2>Cycle History</h2><span class="section-count">' + str(len(cycles)) + ' cycles</span></div>', unsafe_allow_html=True)

    cycle_rows = []
    for c in cycles[:20]:
        ts = c.get("ts_utc", "")
        try:
            dt = datetime.fromisoformat(ts)
            ts_fmt = dt.strftime("%m/%d %H:%M:%S")
        except Exception:
            ts_fmt = str(ts)[:19]
        sig_count = len(c.get("signals", []))
        ord_count = len(c.get("orders", []))
        exit_count = len(c.get("exits", []))
        eq = c.get("equity", 0)
        halted_c = "HALTED" if c.get("halted") else "ACTIVE"
        cycle_rows.append({
            "Time": ts_fmt,
            "Signals": sig_count,
            "Orders": ord_count,
            "Exits": exit_count,
            "Equity": format_equity(eq),
            "Status": halted_c,
        })

    if cycle_rows:
        df_cycles = pd.DataFrame(cycle_rows)
        st.dataframe(df_cycles, use_container_width=True, hide_index=True)

    # ── Footer ───────────────────────────────────────────────────────────
    st.markdown(f"""
    <div class="footer">
        <span>ICT OPTIONS AGENT v1.0</span>
        <span>Mock LLM · Deterministic Risk · Alpaca Paper</span>
        <span>{now_et_str()}</span>
    </div>
    """, unsafe_allow_html=True)
