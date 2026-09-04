"""Plans — Strategy Config & Backtest Results"""
import json
from pathlib import Path
import streamlit as st
import pandas as pd
from config import settings

st.set_page_config(page_title="Plans", page_icon="📋", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"] { font-family: 'JetBrains Mono', monospace; background: #08090C; color: #E2E8F0; }
#MainMenu {visibility:hidden;} footer {visibility:hidden;}
h2 { font-size:0.85rem !important; font-weight:600 !important; color:#8B949E !important; text-transform:uppercase !important; letter-spacing:0.1em !important; margin-top:1.5rem !important; padding-bottom:0.5rem !important; border-bottom:1px solid #21262D !important; }
.config-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:1rem; margin-bottom:1.5rem; }
.config-card { background:#161B22; border:1px solid #30363D; border-radius:8px; padding:1rem; }
.config-card .label { font-size:0.65rem; color:#8B949E; text-transform:uppercase; letter-spacing:0.08em; }
.config-card .value { font-size:1.2rem; font-weight:700; color:#F6F8FA; margin-top:0.25rem; }
.plan-card { background:#161B22; border:1px solid #30363D; border-radius:10px; padding:1.5rem; margin-bottom:1rem; }
.plan-card h3 { margin:0 0 0.75rem 0; font-size:1rem; color:#F6F8FA; }
.plan-card p { font-size:0.8rem; color:#8B949E; line-height:1.6; }
.stDataFrame { border-radius:8px; } .stDataFrame table { background:#161B22; }
.stDataFrame td, .stDataFrame th { border-color:#21262D !important; color:#E2E8F0 !important; font-size:0.78rem !important; padding:0.6rem 0.75rem !important; }
.stDataFrame th { background:#0D1117 !important; color:#8B949E !important; text-transform:uppercase; letter-spacing:0.08em; font-size:0.68rem !important; }
</style>
""", unsafe_allow_html=True)

# ── Risk Configuration ─────────────────────────────────────────────────────────
st.markdown("### RISK CONFIGURATION")
st.markdown('<div class="config-grid">', unsafe_allow_html=True)
risk_items = [
    ("Risk Per Trade", f"{settings.RISK_PCT*100:.2f}%"),
    ("Max Positions", str(settings.MAX_POSITIONS)),
    ("Contracts/Trade", str(settings.MAX_CONTRACTS_PER_TRADE)),
    ("Daily Loss Limit", f"{settings.MAX_DAILY_LOSS_PCT*100:.1f}%"),
    ("Profit Target", f"{settings.PROFIT_TARGET_PCT*100:.0f}%"),
    ("Stop Loss", f"{settings.STOP_LOSS_PCT*100:.0f}%"),
    ("Max DTE to Hold", f"{settings.MAX_DTE_TO_HOLD} days"),
    ("Min DTE", f"{settings.MIN_DTE} days"),
    ("Max DTE", f"{settings.MAX_DTE} days"),
]
for label, value in risk_items:
    st.markdown(f'<div class="config-card"><div class="label">{label}</div><div class="value">{value}</div></div>', unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

# ── Underlying Universe ───────────────────────────────────────────────────────
st.markdown("### UNDERLYING UNIVERSE")
symbols = getattr(settings, 'UNDERLYINGS', ['SPY', 'QQQ'])
st.markdown(f"**Active:** {', '.join(symbols)}")
st.markdown("**Filter:** MIN_OPEN_INTEREST=50 · MAX_QUOTE_SPREAD=25% · MIN_TIME_SCORE=0.35")

# ── Time Windows ───────────────────────────────────────────────────────────────
st.markdown("### ICT TIME WINDOWS")
windows = [
    ("Asian Range", "20:00–00:00", "Context / liquidity only"),
    ("London Open", "02:00–05:00", "Judas / manipulation"),
    ("NY Pre-Open", "08:00–09:30", "Building range"),
    ("NY Open", "09:30–10:00", "Equity open displacement"),
    ("Silver Bullet", "10:00–11:00", "★ Highest priority"),
    ("London Close", "10:00–12:00", "Overlap with Silver Bullet"),
    ("NY PM", "14:00–15:00", "Afternoon secondary"),
]
st.markdown('| Window | Time (ET) | Notes |', unsafe_allow_html=True)
for name, time, note in windows:
    priority = " ⭐" if "silver" in name.lower() or "ny_open" in name.lower() else ""
    st.markdown(f"| {name}{priority} | {time} | {note} |", unsafe_allow_html=True)

# ── Backtest Results ───────────────────────────────────────────────────────────
st.markdown("### BACKTEST RESULTS")
bt_dir = Path("logs/backtest")
if bt_dir.exists():
    files = sorted(bt_dir.glob("*.json"), reverse=True)
    if files:
        for f in files[:5]:
            try:
                d = json.loads(f.read_text())
                st.markdown(f"**{d.get('symbol','?')}** ({d.get('start','')[:10]} → {d.get('end','')[:10]})")
                rows = [
                    ("Trades", str(d.get("trades",0))),
                    ("Win Rate", f"{d.get('win_rate',0)*100:.0f}%"),
                    ("Total P&L", f"${d.get('total_pnl',0):,.2f}"),
                    ("Return", f"{d.get('return_pct',0):.2f}%"),
                    ("Profit Factor", f"{d.get('profit_factor',0):.2f}"),
                    ("Expectancy (R)", f"{d.get('expectancy_r',0):.3f}"),
                    ("Max Drawdown", f"{d.get('max_drawdown_pct',0):.2f}%"),
                ]
                st.markdown('<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.5rem;margin-bottom:1rem">', unsafe_allow_html=True)
                for label, value in rows:
                    color = ""
                    if "P&L" in label and float(value.replace("$","").replace(",","")) < 0: color = "color:#FF4444"
                    if "Return" in label and float(value.replace("%","")) < 0: color = "color:#FF4444"
                    st.markdown(f'<div style="background:#161B22;border:1px solid #30363D;border-radius:6px;padding:0.75rem"><div style="font-size:0.65rem;color:#8B949E;text-transform:uppercase">{label}</div><div style="font-size:1rem;font-weight:700;color:#F6F8FA;{color}">{value}</div></div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
            except: pass
else:
    st.caption("No backtest results found. Run: `python src/main.py --backtest --symbol SPY --start 2025-01-01 --end 2025-06-30`")

# ── Strategy Rules ─────────────────────────────────────────────────────────────
st.markdown("### STRATEGY RULES")
st.markdown("""
<div class="plan-card">
    <h3>🎯 Entry Criteria</h3>
    <p>
    • ICT confluence score ≥ 0.55 (combined score from sweep, MSS, FVG, PD zone)<br>
    • Time score ≥ 0.35 (within primary kill zones: NY Open, Silver Bullet, London Close)<br>
    • No Seek & Destroy warning active<br>
    • Options chain available with liquid contracts (OI ≥ 50)<br>
    • Quote spread ≤ 25% of mid price
    </p>
</div>
<div class="plan-card">
    <h3>🛡️ Risk Controls</h3>
    <p>
    • Max 4 concurrent positions across all underlyings<br>
    • Per-trade risk capped at 0.75% of equity<br>
    • Portfolio delta cap: 50 (absolute sum of signed deltas)<br>
    • Daily loss limit: 3% — triggers hard flatten for rest of day<br>
    • Kill switch auto-flatten enabled
    </p>
</div>
<div class="plan-card">
    <h3>📤 Exit Rules</h3>
    <p>
    • Profit target: +50% unrealized P&L on position<br>
    • Stop loss: -50% unrealized P&L on position<br>
    • Max DTE hold: close any option with ≤ 2 days to expiration<br>
    • EOD flatten: disabled (can enable in .env)<br>
    • AI post-trade reassessment every 15 minutes
    </p>
</div>
""", unsafe_allow_html=True)
