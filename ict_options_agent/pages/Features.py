"""Features — Architecture & Capabilities"""
import streamlit as st
from pathlib import Path

st.set_page_config(page_title="Features", page_icon="⚡", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"] { font-family: 'JetBrains Mono', monospace; background: #08090C; color: #E2E8F0; }
#MainMenu {visibility:hidden;} footer {visibility:hidden;}
h2 { font-size:0.85rem !important; font-weight:600 !important; color:#8B949E !important; text-transform:uppercase !important; letter-spacing:0.1em !important; margin-top:1.5rem !important; padding-bottom:0.5rem !important; border-bottom:1px solid #21262D !important; }
.feature-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:1rem; margin-bottom:1.5rem; }
.feature-card { background:#161B22; border:1px solid #30363D; border-radius:10px; padding:1.25rem; }
.feature-card h3 { margin:0 0 0.5rem 0; font-size:0.95rem; color:#F6F8FA; }
.feature-card p { font-size:0.78rem; color:#8B949E; line-height:1.6; margin:0; }
.feature-card .tag { display:inline-block; background:rgba(88,166,255,0.1); border:1px solid rgba(88,166,255,0.3); color:#58A6FF; font-size:0.65rem; padding:0.15rem 0.5rem; border-radius:4px; margin-top:0.5rem; }
.arch-diagram { background:#0D1117; border:1px solid #21262D; border-radius:8px; padding:1.5rem; margin:1rem 0; font-size:0.8rem; color:#8B949E; line-height:1.8; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div style="padding:1rem 0;border-bottom:1px solid #21262D;margin-bottom:1.5rem">
    <h1 style="margin:0;font-size:1.5rem;font-weight:700;color:#F6F8FA">⚡ ICT Options Agent — Features</h1>
    <div style="font-size:0.75rem;color:#8B949E;letter-spacing:0.1em;text-transform:uppercase;margin-top:0.25rem">
        Confluence Analysis · AI Reasoning · Options Execution
    </div>
</div>
""", unsafe_allow_html=True)

# ── Core Features ──────────────────────────────────────────────────────────────
st.markdown("### CORE FEATURES")
st.markdown('<div class="feature-grid">', unsafe_allow_html=True)

features = [
    ("🧠 Mock LLM Engine",
     "ICT-grounded decision engine that reasons over real market evidence — sweeps, FVGs, MSS, S&D patterns. No OpenAI key required. Produces TRADE/WAIT decisions with full rationale and adversarial review.",
     "AI / Reasoning"),
    ("📊 RTH Session Engine",
     "Builds structured market state from 1m/5m/15m bars. Classifies session phase (AM/Lunch/PM), computes directional bias, and scores ICT confluence across multiple timeframes.",
     "Detection"),
    ("🎯 ICT Pattern Detection",
     "Detects liquidity sweeps, fair value gaps (FVG), market structure shifts (MSS), seeking & destroying patterns, dealing ranges, and order blocks. Multi-timeframe analysis.",
     "Signals"),
    ("🛡️ Deterministic Risk Governor",
     "Hard-coded risk controls are final authority — never overridden by AI. Enforces kill switch, position limits, daily loss caps, delta exposure limits, and quote quality gates.",
     "Risk"),
    ("📈 Options Chain Intelligence",
     "Fetches live option chains, analyzes DTE, moneyness, open interest, and quote spreads. Recommends optimal spread structures (bull call, bear put, iron condor).",
     "Execution"),
    ("🔒 Idempotent Order Execution",
     "Every order gets a deterministic client_order_id. Restarts won't double-fill. Routes through MCP → CLI → SDK fallback for reliability.",
     "Safety"),
    ("📋 Per-Cycle Audit Trail",
     "Every cycle writes a JSON audit file with full signal evidence, AI decision, risk checks, and order results. Reconstructable from logs/audit/.",
     "Audit"),
    ("🔬 Autonomous Research Loop",
     "Generates falsifiable hypotheses from accepted trades, tracks observations, and learns from outcomes. Maintains a bounded memory of recent research.",
     "Learning"),
]

for title, desc, tag in features:
    st.markdown(f"""
    <div class="feature-card">
        <h3>{title}</h3>
        <p>{desc}</p>
        <span class="tag">{tag}</span>
    </div>
    """, unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)

# ── Architecture ───────────────────────────────────────────────────────────────
st.markdown("### ARCHITECTURE")
st.markdown("""
<div class="arch-diagram">
<strong>┌─────────────────────────────────────────────────────────────────────┐</strong><br>
<strong>│                      LOCAL PROCESS (Python)                         │</strong><br>
<strong>│                                                                     │</strong><br>
<strong>│  CLI (main.py) ──→ Agent (agent.py) ──→ RTH Engine                  │</strong><br>
<strong>│                           │                    │                    │</strong><br>
<strong>│                     Position Mgmt          ICT Detectors            │</strong><br>
<strong>│                           │                    │                    │</strong><br>
<strong>│                      Manage                  Mock LLM ←── Options   │</strong><br>
<strong>│                           │                    │       Chain        │</strong><br>
<strong>│                      Exits               Adversarial Review         │</strong><br>
<strong>│                           │                    │                    │</strong><br>
<strong>│                      Risk Governor ──→ Order Exec                      │</strong><br>
<strong>│                           │                    │                    │</strong><br>
<strong>│                      SQLite              Alpaca API (Paper)          │</strong><br>
<strong>│                           │                    │                    │</strong><br>
<strong>│                      Audit JSON ──→ Streamlit :8506                 │</strong><br>
<strong>│                                                                     │</strong><br>
<strong>└─────────────────────────────────────────────────────────────────────┘</strong>
</div>
""", unsafe_allow_html=True)

# ── Diagrams Link ──────────────────────────────────────────────────────────────
st.markdown("### VISUAL DIAGRAMS")
diagrams_dir = Path("docs/diagrams")
if diagrams_dir.exists():
    for f in sorted(diagrams_dir.glob("*.html")):
        if "visual-check" not in f.name:
            st.markdown(f"- **{f.stem.replace('agent-','').replace('-',' ')}** — [{f.name}]({f})")
else:
    st.caption("Run `node archify-diagrams.mjs` to generate diagrams")

# ── How It Works ───────────────────────────────────────────────────────────────
st.markdown("### HOW THE AGENT WORKS")
st.markdown("""
1. **Cycle Start** — Every 5 minutes, the agent wakes up and checks kill-switch status
2. **Data Fetch** — Pulls 1m/5m/15m bars from Alpaca for SPY, QQQ, IWM, AAPL, NVDA
3. **RTH State** — Builds session state: phase (AM/Lunch/PM), bias, combined score
4. **Signal Detection** — Runs ICT detectors: sweeps, FVGs, MSS, S&D, dealing range
5. **Options Chain** — Fetches live chain, filters by DTE 3-14, OI ≥ 50, quote quality
6. **AI Decision** — Mock LLM reasons over evidence → TRADE or WAIT with rationale
7. **Adversarial Review** — Second-pass challenger tries to disprove the thesis
8. **Risk Check** — Deterministic governor enforces all risk limits (final authority)
9. **Order Execution** — Places MLEG order via MCP → CLI → SDK with idempotency key
10. **Audit** — Writes cycle JSON to logs/audit/ for reproducibility and dashboard display
11. **Position Management** — Monitors open positions for exits (target/stop/DTE)

<strong style="color:#3FB950">Key Principle:</strong> The AI suggests, the deterministic risk layer disposes.
""", unsafe_allow_html=True)

# ── Tech Stack ─────────────────────────────────────────────────────────────────
st.markdown("### TECH STACK")
st.markdown("| Component | Technology | Purpose |", unsafe_allow_html=True)
st.markdown("|-----------|-----------|---------|", unsafe_allow_html=True)
stack = [
    ("Python 3.12", "Language", "Core logic"),
    ("Alpaca SDK", "Brokerage API", "Paper trading execution"),
    ("Mock LLM", "Custom reasoning", "ICT-grounded decisions without OpenAI"),
    ("Streamlit", "Dashboard UI", "Live monitoring at :8506"),
    ("SQLite", "Persistence", "Positions, orders, daily stats"),
    ("Archify", "Diagramming", "Architecture visualization"),
    ("loguru", "Logging", "Structured logging to files"),
]
for tech, category, purpose in stack:
    st.markdown(f"| {tech} | {category} | {purpose} |", unsafe_allow_html=True)
