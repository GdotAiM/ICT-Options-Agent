# ICT Options Agent

<div align="center">

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.28+-FF4B4B.svg)](https://streamlit.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**AI-powered options trading agent with ICT methodology & real Nemotron 120B**

[Features](#features) • [Quick Start](#quick-start) • [Dashboard](#dashboard) • [Docs](docs/)

</div>

---

## 🎯 Overview

ICT Options Agent is a production-ready AI trading system that combines **Intermarket Analysis Theory (ICT)** concepts with **real machine learning** (Nvidia Nemotron 120B via OpenRouter) to identify and execute options trades.

### Why This Project Stands Out

| Feature | Implementation |
|---------|----------------|
| **Real AI** | Nemotron 120B via OpenRouter — NOT a mock LLM |
| **Professional Dashboard** | Premium dark theme with interactive charts |
| **Complete Audit Trail** | Every decision logged with full evidence chain |
| **Production Code** | Type hints, error handling, idempotent execution |
| **Visual Documentation** | 4 architecture diagrams + submission guide |

---

## ✨ Features

### Trading Engine
- ✅ **Real-time Monitoring** — Scans SPY, QQQ, IWM, AAPL, NVDA every 5 minutes
- ✅ **ICT Pattern Detection** — Sweeps, FVGs, MSS, S&D, order blocks, dealing ranges
- ✅ **Multi-Timeframe Analysis** — 1m, 5m, 15m bars + 15s micro-bars
- ✅ **Options Chain Intelligence** — DTE, moneyness, OI, quote quality filters
- ✅ **AI Reasoning** — Nemotron 120B evaluates evidence with adversarial review
- ✅ **Risk Management** — Kill switch, position sizing, delta caps, daily loss limits

### Dashboard & Visualization
- ✅ **Premium Dark Theme** — Terminal-style UI matching professional platforms
- ✅ **Equity Curve Chart** — Interactive Plotly visualization
- ✅ **Trading Calendar** — Monthly heatmap showing daily P&L
- ✅ **Live Positions** — Real-time Alpaca paper account data
- ✅ **Order History** — Complete audit trail
- ✅ **Architecture Diagrams** — 4 types generated with Archify

---

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Alpaca Paper Trading Account ([sign up free](https://alpaca.markets/))
- OpenRouter API Key ([get key](https://openrouter.ai/))

### Installation

```bash
# Clone repository
git clone https://github.com/GdotAiM/ICT-Options-Agent.git
cd ICT-Options-Agent

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp ict_options_agent/.env.example ict_options_agent/.env
# Edit .env with your API keys
```

### Run the System

```bash
cd ict_options_agent

# Start dashboard (recommended)
PYTHONPATH=. streamlit run streamlit_app.py --server.port 8520

# Or run agent manually
PYTHONPATH=. python src/main.py --once --symbol SPY

# Or continuous loop
PYTHONPATH=. python src/main.py --loop --interval 300
```

---

## 📊 Dashboard

Access at **http://localhost:8520**

### Pages

| Page | Description |
|------|-------------|
| **Home** | Overview with metrics and recent activity |
| **Account** | Equity curve, trading calendar, performance |
| **Positions** | Live positions and order history from Alpaca |
| **Plans** | Strategy configuration and backtest results |
| **Features** | Architecture diagrams and capabilities |

---

## 📚 Documentation

All documentation is in the `docs/` directory:

- **[docs/SUBMISSION_GUIDE.md](docs/SUBMISSION_GUIDE.md)** — Complete submission documentation
- **[docs/diagrams/](docs/diagrams/)** — 4 interactive HTML architecture diagrams
- **[docs/README.md](docs/README.md)** — Documentation index

### Architecture Diagrams

Generate diagrams anytime:
```bash
node archify-diagrams.mjs
```

---

## ⚙️ Configuration

### Required Environment Variables

```bash
# Alpaca Paper Trading
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
ALPACA_PAPER=true

# AI/LLM (using OpenRouter)
LLM_PROVIDER=openai
LLM_MODEL=openrouter/nvidia/nemotron-3-super-120b-a12b:free
OPENAI_API_KEY=sk-or-v1-your_key_here
LLM_BASE_URL=https://openrouter.ai/api/v1
```

### Risk Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `RISK_PCT` | 0.0075 | Risk per trade (0.75%) |
| `MAX_POSITIONS` | 4 | Max concurrent positions |
| `MAX_DAILY_LOSS_PCT` | 0.03 | Daily loss limit (3%) |
| `PROFIT_TARGET_PCT` | 0.50 | Take profit (50%) |
| `STOP_LOSS_PCT` | -0.50 | Stop loss (-50%) |

---

## 🧪 Testing

```bash
cd ict_options_agent

# Run tests
pytest tests/ -v

# Backtest example
PYTHONPATH=. python src/main.py --backtest --symbol SPY --start 2025-01-01 --end 2025-06-30
```

---

## 📁 Project Structure

```
ICT-Options-Agent/
├── README.md                      # This file
├── requirements.txt               # Python dependencies
├── archify-diagrams.mjs          # Diagram generation script
├── docs/
│   ├── SUBMISSION_GUIDE.md       # Complete submission documentation
│   └── diagrams/                  # 4 architecture diagrams
├── archive/                       # Archived old versions
└── ict_options_agent/
    ├── .env                       # Environment config (DO NOT COMMIT)
    ├── streamlit_app.py           # Main dashboard entry point
    ├── pages/                     # Multi-page dashboard
    │   ├── Home.py
    │   ├── Account.py            # Equity + Calendar
    │   ├── Positions.py          # Live Alpaca data
    │   ├── Plans.py
    │   └── Features.py
    ├── src/                       # Core logic
    │   ├── agent.py              # Main agent orchestration
    │   ├── llm_agent.py          # AI reasoning engine
    │   ├── rth_engine.py         # Session state builder
    │   ├── risk.py               # Risk management
    │   └── ...                   # Other modules
    ├── tests/                     # Test suite
    └── logs/                      # Runtime logs
```

---

## 🔧 Recent Updates

### v1.1.0 (2026-09-04)
- ✅ Upgraded to real LLM (Nemotron 120B via OpenRouter)
- ✅ Added premium dashboard with trading calendar
- ✅ Implemented equity curve visualization
- ✅ Fixed timezone handling (UTC → ET)
- ✅ Generated architecture diagrams with Archify
- ✅ Enhanced risk management with adversarial review

### v1.0.0 (Initial)
- ✅ Cloned original ICT-Options-Agent
- ✅ Added mock LLM fallback
- ✅ Fixed audit trail field names
- ✅ Integrated with Alpaca paper trading

---

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License.

---

## 🙏 Acknowledgments

- **ICT (Inner Circle Trader)** — Trading methodology
- **Alpaca Markets** — Paper trading API
- **OpenRouter** — AI model aggregation
- **Nvidia Nemotron** — Open-source language models
- **Streamlit** — Dashboard framework
- **Archify** — Architecture diagramming

---

<div align="center">

**Built with ❤️ for algorithmic trading**

📧 Questions? Open an issue or contact the maintainers.

</div>
