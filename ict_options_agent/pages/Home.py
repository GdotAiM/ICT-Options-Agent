"""Dashboard — Home Overview"""
import json
from pathlib import Path
from datetime import datetime
import streamlit as st
import pandas as pd
import pytz
from config import settings

st.set_page_config(page_title="Home", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
html, body, [class*="css"] { font-family: 'JetBrains Mono', monospace; background: #08090C; color: #E2E8F0; }
#MainMenu {visibility:hidden;} footer {visibility:hidden;}
.hero { display:flex; justify-content:space-between; padding:1rem 0 1.5rem; border-bottom:1px solid #21262D; margin-bottom:1rem; }
.hero h1 { margin:0; font-size:1.5rem; font-weight:700; color:#F6F8FA; }
.hero .subtitle { font-size:0.7rem; color:#8B949E; letter-spacing:0.1em; text-transform:uppercase; margin-top:0.2rem; }
.metrics-row { display:grid; grid-template-columns:repeat(4,1fr); gap:1rem; margin-bottom:1.5rem; }
.metric-card { background:linear-gradient(135deg,#161B22 0%,#0D1117 100%); border:1px solid #30363D; border-radius:10px; padding:1rem 1.25rem; position:relative; overflow:hidden; }
.metric-card::before { content:''; position:absolute; top:0; left:0; right:0; height:2px; border-radius:10px 10px 0 0; }
.metric-card.status::before { background:linear-gradient(90deg,#3FB950,#238636); }
.metric-card.equity::before { background:linear-gradient(90deg,#58A6FF,#1F6FEB); }
.metric-card.positions::before { background:linear-gradient(90deg,#D29922,#BB8009); }
.metric-card.activity::before { background:linear-gradient(90deg,#BC8Cff,#8957e5); }
.metric-label { font-size:0.65rem; color:#8B949E; text-transform:uppercase; letter-spacing:0.1em; margin-bottom:0.5rem; }
.metric-value { font-size:1.5rem; font-weight:700; color:#F6F8FA; }
.metric-sub { font-size:0.7rem; color:#8B949E; margin-top:0.3rem; }
.status-pill { display:inline-flex; align-items:center; gap:0.5rem; padding:0.35rem 0.85rem; border-radius:20px; font-size:0.75rem; font-weight:600; }
.status-pill.online { background:rgba(63,185,80,0.1); border:1px solid rgba(63,185,80,0.4); color:#3FB950; }
.status-dot { width:7px; height:7px; border-radius:50%; background:currentColor; animation:blink 2s infinite; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
.positions-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:0.75rem; margin-bottom:1.5rem; }
.position-card { background:#161B22; border:1px solid #30363D; border-radius:8px; padding:0.85rem 1rem; display:flex; justify-content:space-between; align-items:center; }
.position-card.profit { border-left:3px solid #3FB950; }
.position-card.loss { border-left:3px solid #FF4444; }
.pos-symbol { font-size:0.85rem; font-weight:600; }
.pos-pnl { font-size:1rem; font-weight:700; text-align:right; }
.pnl-pos { color:#3FB950; } .pnl-neg { color:#FF4444; }
.stDataFrame { border-radius:8px; }
.stDataFrame table { background:#161B22; }
.stDataFrame td, .stDataFrame th { border-color:#21262D !important; color:#E2E8F0 !important; font-size:0.78rem !important; padding:0.6rem 0.75rem !important; }
.stDataFrame th { background:#0D1117 !important; color:#8B949E !important; text-transform:uppercase; letter-spacing:0.08em; font-size:0.68rem !important; }
h2 { font-size:0.85rem !important; font-weight:600 !important; color:#8B949E !important; text-transform:uppercase !important; letter-spacing:0.1em !important; margin-top:1.5rem !important; padding-bottom:0.5rem !important; border-bottom:1px solid #21262D !important; }
</style>
""", unsafe_allow_html=True)

# ── Load Data ──────────────────────────────────────────────────────────────────
def load_cycles():
    audit_dir = Path(settings.AUDIT_DIR)
    files = sorted(audit_dir.glob("cycle_*.json"), reverse=True) if audit_dir.exists() else []
    cycles = []
    for f in files[:30]:
        try:
            d = json.loads(f.read_text())
            cycles.append(d)
        except: pass
    return cycles

cycles = load_cycles()
latest = cycles[0] if cycles else {}

# ── Hero ───────────────────────────────────────────────────────────────────────
et_now = datetime.now(pytz.timezone("US/Eastern"))
market_open = 9 <= et_now.hour < 16
st.markdown(f"""
<div class="hero">
    <div>
        <h1>📊 ICT OPTIONS AGENT</h1>
        <div class="subtitle">Confluence Analysis · AI Reasoning · Options Execution</div>
    </div>
    <div style="text-align:right">
        <div style="font-size:1.1rem;color:#F6F8FA;font-weight:600">{et_now.strftime("%H:%M:%S")}</div>
        <div style="font-size:0.7rem;color:#8B949E">ET · Market: {"OPEN" if market_open else "PRE-MARKET"}</div>
    </div>
</div>
""", unsafe_allow_html=True)

if not cycles:
    st.markdown('<div style="text-align:center;padding:3rem;color:#8B949E">No cycles yet. Run agent with: <code>python src/main.py --loop</code></div>', unsafe_allow_html=True)
else:
    equity = latest.get("equity", 0)
    day_start = latest.get("day_starting_equity", equity)
    pnl_pct = ((equity - day_start) / day_start * 100) if day_start > 0 else 0
    is_halted = latest.get("halted", False)
    positions = latest.get("positions_snapshot") or latest.get("positions", [])
    signals = latest.get("signals", [])

    # ── Metrics ──────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div class="metrics-row">
        <div class="metric-card status">
            <div class="metric-label">Agent Status</div>
            <div class="metric-value"><span class="status-pill {'online' if not is_halted else 'halted'}"><span class="status-dot"></span>{'ONLINE' if not is_halted else 'KILLED'}</span></div>
            <div class="metric-sub">Mode: {latest.get('mode','?').upper()}</div>
        </div>
        <div class="metric-card equity">
            <div class="metric-label">Equity</div>
            <div class="metric-value">${equity:,.2f}</div>
            <div class="metric-sub" style="color:{'#3FB950' if pnl_pct>=0 else '#FF4444'}">{pnl_pct:+.2f}% today</div>
        </div>
        <div class="metric-card positions">
            <div class="metric-label">Open Positions</div>
            <div class="metric-value">{len(positions)}</div>
            <div class="metric-sub">Max: {settings.MAX_POSITIONS}</div>
        </div>
        <div class="metric-card activity">
            <div class="metric-label">Cycle Activity</div>
            <div class="metric-value" style="font-size:1.2rem">{len(signals)} signals</div>
            <div class="metric-sub"><span style="color:#3FB950">0 TRADE</span> · <span style="color:#D29922">{len(signals)} WAIT</span></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Positions ────────────────────────────────────────────────────────────
    if positions:
        st.markdown("### OPEN POSITIONS")
        st.markdown('<div class="positions-grid">', unsafe_allow_html=True)
        for pos in positions:
            sym_raw = pos.get("symbol", "?")
            sym = sym_raw[:3]
            qty = pos.get("qty", "0")
            pl = float(pos.get("unrealized_plpc") or 0) * 100
            mv = float(pos.get("market_value") or 0)
            cls = "profit" if pl > 0 else "loss"
            pnl_cls = "pnl-pos" if pl > 0 else "pnl-neg"
            try:
                exp = sym_raw[3:11]
                strike = float(sym_raw[11:]) / 1000
                clean = f"{sym} {exp} ${strike:.0f}"
            except:
                clean = sym_raw
            st.markdown(f"""
            <div class="position-card {cls}">
                <div><div class="pos-symbol">{clean}</div><div style="font-size:0.65rem;color:#8B949E">qty={qty} · MV=${mv:,.0f}</div></div>
                <div class="pos-pnl {pnl_cls}">{pl:+.1f}%</div>
            </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Recent Cycles ────────────────────────────────────────────────────────
    st.markdown("### RECENT CYCLES")
    rows = []
    for c in cycles[:15]:
        ts = c.get("ts_utc","")[:19].replace("T"," ")
        eq = c.get("equity",0)
        pos = len(c.get("positions_snapshot") or c.get("positions",[]))
        sig = len(c.get("signals",[]))
        rows.append({"Time": ts, "Signals": sig, "Positions": pos, "Equity": f"${eq:,.2f}", "Halt": "YES" if c.get("halted") else "-"})
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
