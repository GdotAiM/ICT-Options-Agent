# ICT Options Agent — Submission Guide

## Project Summary

The ICT Options Agent is a production-ready AI trading system that combines Intermarket Analysis Theory (ICT) methodology with real machine learning to identify and execute options trades. The system operates 24/7, monitoring market conditions and executing trades based on detected patterns while enforcing strict risk management controls.

## What Makes This Project Stand Out

### 1. Real AI Integration (Not Mock)
Unlike many trading bot projects that use dummy LLMs for demo purposes, this implementation uses **Nvidia Nemotron 120B** via OpenRouter — a genuine 120-billion parameter model that provides actual reasoning over market evidence.

**Evidence:**
- Configuration in `.env`: `LLM_MODEL=openrouter/nvidia/nemotron-3-super-120b-a12b:free`
- API calls to real OpenRouter endpoints
- Adversarial review system that challenges trade proposals

### 2. Professional-Grade Dashboard
The Streamlit dashboard isn't a basic CRUD app — it's a **trading terminal** featuring:
- Interactive equity curve charts (Plotly)
- Monthly trading calendar heatmaps
- Live position tracking from Alpaca
- Architecture diagrams (generated with Archify)

**Evidence:**
- 5-page navigation system (Home, Account, Plans, Features, Positions)
- Custom CSS with dark theme matching professional trading platforms
- Real-time data updates every 30 seconds

### 3. Complete Audit Trail
Every decision is logged with full evidence:
- ICT signal scores and patterns detected
- AI reasoning and rationale
- Risk checks performed
- Order execution details
- Post-trade assessments

**Evidence:**
- JSON audit files in `logs/audit/`
- Structured logging with loguru
- Reconstructable decision chains

### 4. Production-Ready Code
The codebase follows production standards:
- Type hints throughout
- Error handling and retry logic
- Idempotent order execution (prevents duplicate fills)
- SSL certificate handling for Windows
- Modular architecture with clear separation of concerns

## Technical Implementation

### Core Components

#### 1. AI Reasoning Engine (`src/llm_agent.py`)
- System prompt defines ICT framework and decision rules
- Receives structured evidence packet (scores, patterns, chain data)
- Outputs TRADE/WAIT decisions with confidence scores
- Adversarial challenger reviews proposals for contradictions
- Post-trade monitor reassesses open positions

#### 2. ICT Pattern Detection (`src/rth_engine.py`, `src/ict_detectors.py`)
- RTH (Regular Trading Hours) engine builds session state
- Detects: Liquidity sweeps, Fair Value Gaps (FVGs), Market Structure Shifts (MSS)
- Identify: Seeking & Destroying (S&D) patterns, Order blocks
- Multi-timeframe analysis (1m, 5m, 15m, plus 15s micro-bars)

#### 3. Risk Management (`src/risk.py`)
- Kill switch: Halts all trading after daily loss threshold
- Position sizing: Calculates contracts based on risk percentage
- Delta exposure: Caps total portfolio delta
- Quote quality: Rejects illiquid or wide-spread quotes

#### 4. Execution Layer (`src/mcp_exec.py`, `src/agent.py`)
- Multi-leg order construction (debit spreads, iron condors)
- Idempotency keys prevent duplicate fills on restart
- Fallback chain: MCP → CLI → SDK
- State persistence in SQLite

### Dashboard Architecture

#### Page Structure
```
pages/
├── Home.py          — Overview, metrics, recent activity
├── Account.py       — Equity curve, trading calendar, performance
├── Positions.py     — Live positions, order history, P&L
├── Plans.py         — Strategy config, backtest results, rules
└── Features.py      — Architecture, capabilities, tech stack
```

#### Key Visualizations
1. **Equity Curve** (Plotly)
   - Line chart with filled area
   - Start equity reference line
   - Hover tooltips with exact values
   - Stats: Current, Change, High, Low

2. **Trading Calendar** (Custom HTML/CSS)
   - Monthly grid layout
   - Color coding: Green (profit), Red (loss), Gray (inactive)
   - Cell content: $P&L amount + trade count
   - Summary row: Total P&L, Win/Loss days

3. **Position Cards**
   - Gradient borders based on P&L direction
   - Clean typography with monospace font
   - One card per option leg

## How to Run

### Prerequisites
```bash
# Python 3.12+
python --version

# Install dependencies
pip install -r requirements.txt
```

### Configuration
```bash
# Copy environment template
cp ict_options_agent/.env.example ict_options_agent/.env

# Edit with your credentials
# Required: Alpaca API keys, OpenRouter API key
```

### Start Dashboard
```bash
cd ict_options_agent
PYTHONPATH=. streamlit run streamlit_app.py --server.port 8520
```

### Access Dashboard
```
http://localhost:8520
```

## Demo Evidence

### Screenshots Available
- `Screenshot 2026-09-04 154959.png` — Account page with calendar
- `Screenshot 2026-09-04 153438.png` — Dashboard overview
- `Screenshot 2026-09-04 152504.png` — Positions and orders

### Live Data
- Connected to Alpaca Paper Trading
- Real equity: ~$100,085
- Open positions: 4 option spreads
- Active monitoring: Every 5 minutes

## Files for Review

### Core Code
- `ict_options_agent/src/agent.py` — Main agent orchestration
- `ict_options_agent/src/llm_agent.py` — AI reasoning layer
- `ict_options_agent/src/rth_engine.py` — Session state builder
- `ict_options_agent/src/risk.py` — Risk management
- `ict_options_agent/pages/*.py` — Dashboard pages

### Configuration
- `ict_options_agent/.env` — API keys and settings
- `requirements.txt` — Python dependencies
- `archify-diagrams.mjs` — Diagram generation pipeline

### Documentation
- `README.md` — Project overview
- `docs/diagrams/*.html` — Architecture visualizations
- `docs/SUBMISSION_GUIDE.md` — This file

## Key Innovations

1. **Hybrid AI-Deterministic System**
   - AI handles pattern recognition and thesis formation
   - Deterministic code enforces risk limits
   - Fail-closed design (unavailable AI = no trades)

2. **Adversarial Review**
   - Second-pass challenger questions every trade proposal
   - Forces AI to justify convictions
   - Reduces false positives

3. **Evidence-Based Decisions**
   - Every trade backed by ICT confluence scoring
   - Clear invalidation levels defined
   - Audit trail enables post-mortem analysis

4. **Professional Visualization**
   - Trading-grade UI, not basic charts
   - Interactive elements (zoom, pan, hover)
   - Mobile-responsive layout

## Conclusion

This project demonstrates a complete, production-ready AI trading system with:
- Real LLM integration (not mock)
- Professional dashboard with advanced visualizations
- Comprehensive risk management
- Full audit trail and transparency
- Clean, maintainable codebase

It's ready for deployment and can be extended with additional symbols, strategies, or data sources.
