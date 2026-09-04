# ICT Options Agent — Architecture Diagrams

Interactive, self-contained HTML diagrams generated with [Archify](https://github.com/tt-a1i/archify).

## Generated Diagrams

| Diagram | Type | File | Description |
|---------|------|------|-------------|
| **Agent Architecture** | Architecture | [`agent-architecture.html`](agent-architecture.html) | Component map: detection → AI → execution → persistence layers |
| **Trading Cycle Workflow** | Workflow | [`agent-workflow.html`](agent-workflow.html) | Happy path + fail-closed branches through the 5-min cycle |
| **Single Cycle Sequence** | Sequence | [`agent-sequence.html`](agent-sequence.html) | Full call chain: Timer → Alpaca → RTH → LLM → Risk → Order |
| **Market Data Pipeline** | Data Flow | [`agent-dataflow.html`](agent-dataflow.html) | Sources → Ingest → Process → Decide → Execute stages |

## How to Open

Each `.html` file is fully self-contained — just open in any browser:

```bash
# macOS
open docs/diagrams/agent-architecture.html

# Windows
start docs/diagrams/agent-architecture.html

# Linux
xdg-open docs/diagrams/agent-architecture.html
```

Or visit the Streamlit dashboard at http://localhost:8503 which reads the same audit data.

## Interactive Features

- **Focus** (`/`): Search and jump to any component
- **Trace** (`R`): Follow exact routes between nodes
- **Compare Roles** (`L`): See upstream/downstream connections per node
- **Play** (`P`): Animated guided stories through the diagram
- **Theme toggle**: Switch between dark/light mode
- **Export**: PNG, SVG, WebM, and 1200×630 share cards

## Regenerating Diagrams

```bash
cd ~/ICT-Options-Agent
node archify-diagrams.mjs              # regenerate all 4 diagrams
node archify-diagrams.mjs --validate   # validate only (no output files)
```

Requires: [Node.js](https://nodejs.org) ≥ 18, Archify skill installed (`npx skills add tt-a1i/archify -g`).

## Source Code Reference

The JSON specs live alongside the HTML:
- `docs/diagrams/agent-architecture.json` — architecture component map
- `docs/diagrams/agent-workflow.json` — workflow lane/phase model
- `docs/diagrams/agent-sequence.json` — sequence participant/message model
- `docs/diagrams/agent-dataflow.json` — dataflow stage/node/flow model

Edit the JSON directly and re-run `node archify-diagrams.mjs` to regenerate.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                      LOCAL PROCESS                                  │
│                                                                     │
│  CLI ──→ Agent ──→ RTH Engine ──→ ICT Detectors                    │
│                    ↓          ↓                                      │
│                 Risk Gov ──→ Mock LLM ──→ Challenger                │
│                    ↓          ↓         ↓                           │
│                 Order Exec ←── Chain Analyzer                       │
│                    ↓                                                │
│              Alpaca API (paper)    SQLite State DB                   │
│                    ↓                                                │
│              Audit Trail ──→ Streamlit Dashboard :8503              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Key design principles:**
- **Mock LLM** (`mock_llm.py`) provides intelligent decisions without OpenAI keys
- **Deterministic risk governor** is final authority — AI can suggest but never override kill switch, sizing, or delta limits
- **Fail-closed**: Every AI path defaults to WAIT on error/unavailable
- **Idempotent orders**: client_order_id prevents duplicate fills across restarts
- **Per-cycle audit**: Every decision logged to `logs/audit/cycle_*.json`

## Files Changed This Session

- `src/mock_llm.py` — New mock LLM module (ICT-grounded decisions)
- `src/llm_agent.py` — Patched with MOCK_LLM routing
- `src/audit.py` — Added `day_starting_equity` + fixed `positions_snapshot` field name
- `src/agent.py` — Passes `day_start` to audit writer
- `.env` — Paper trading config with `MOCK_LLM=true`
- `docs/diagrams/*.html` — 4 interactive architecture diagrams
- `archify-diagrams.mjs` — Automated diagram generation pipeline
