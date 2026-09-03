# ICT Options Confluence Agent


### Autonomous Research Loop
The agent now treats accepted setups as falsifiable ICT experiments. A research layer creates a hypothesis, explicit confirmation/invalidation conditions, and next observations using recent research memory. During position reassessment it records observations and extracts a learning update. This creates an observe → hypothesize → trade → reassess → learn loop while the deterministic risk/execution constitution remains authoritative.

**An AI trading agent that uses ICT market concepts to reason about options trades, then places only risk-approved defined-risk structures through Alpaca.**

## Why this is different

This is not an LLM guessing whether SPY goes up or down. The system creates a structured **ICT evidence packet** and gives it to an AI reasoning layer.

**Observe → ICT evidence → live options chain → AI thesis → adversarial challenge → options expression → risk constitution → Alpaca → audit → AI reassessment**

The AI interprets:

- Sell-side / buy-side liquidity sweeps
- Market Structure Shift (MSS)
- Fair Value Gaps (FVG)
- Order Blocks (OB)
- Premium / Discount
- Dealing Range, equilibrium, octants and Consequent Encroachment
- NY Open, Silver Bullet, London Close and other kill-zone context
- Opening Range Gap / FPFVG / wick and body imbalance
- Seek & Destroy conditions
- Chain of Custody of Price / liquidity targets

### AI-to-options mapping

| ICT thesis | AI expression |
|---|---|
| Bullish liquidity raid + MSS + discount/PD-array confluence | `BULL_CALL_SPREAD` |
| Bearish liquidity raid + MSS + premium/PD-array confluence | `BEAR_PUT_SPREAD` |
| Genuine range/mean-reversion context without a directional imbalance | `IRON_CONDOR` |
| Conflicting or incomplete evidence | `WAIT` |

The AI **does not invent strikes or premiums**. It sees the live chain before choosing the expression and can request DTE/moneyness constraints. The deterministic options engine then selects real contracts from the same Alpaca chain and applies quote/liquidity gates.

## The AI is a multi-stage reasoning loop

`src/llm_agent.py` contains the ICT-aware reasoning stack. It now runs three AI roles: a primary ICT/options analyst, an adversarial thesis challenger, and a post-trade position monitor. The deterministic engine also supplies a live Alpaca options-chain packet (expiration/DTE, moneyness, bid/ask quality, open interest/volume, IV and Greeks when available).

- `TRADE` or `WAIT`
- directional thesis
- options structure
- confidence (judgment score, not probability of profit)
- required and missing ICT confluences
- entry condition
- invalidation
- target
- rationale

The model is explicitly instructed not to manufacture missing ICT evidence, flip the deterministic bias, recommend naked short options, or bypass safety controls. The challenger is deliberately adversarial: a failed review forces `WAIT`.

### Financial safety remains deterministic

The AI cannot override:

- options Level 3 requirement for MLEG
- quote/liquidity gates
- position limits
- per-trade sizing
- portfolio risk cap
- delta cap
- daily drawdown kill switch
- idempotent order protection
- deterministic exits / DTE management

**AI = reasoning. Code = authority. Alpaca = execution. Audit = accountability.**

## Alpaca + MCP

The execution boundary supports the official Alpaca MCP server and SDK fallback. For the competition demo, enable MCP explicitly and verify the server before trading:

```bash
USE_MCP=true python -m src.main --verify-mcp
```

Then run the agent:

```bash
python -m src.main --once --mode auto
```

`auto` allows the AI to choose the options expression while the execution layer remains responsible for actual contracts, quotes, sizing and risk checks.

## AI configuration

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=...
AI_REQUIRED=true
```

`AI_REQUIRED=true` is recommended for the hackathon/demo path. If the configured LLM is unavailable, the agent fails closed to `WAIT` rather than presenting deterministic fallback output as an AI decision.

## Risk defaults

- 0.75% target risk per trade
- 4% maximum portfolio option risk
- maximum 4 positions
- maximum 10 contracts/trade
- portfolio delta cap
- 3% daily loss circuit breaker with auto-flatten on engagement
- Level 3 options approval required
- OI / quote-quality filters
- idempotent client order IDs
- profit target (+50%) / stop loss (-50%) / low-DTE exits
- complete cycle audit JSON

## Backtest disclaimer

The included backtest is a **synthetic-bar software smoke test** for validating signal and exit mechanics. It is **not historical options P&L** and should not be presented as profitability evidence.

## Dashboard

```bash
streamlit run streamlit_app.py
```

The dashboard exposes the AI decision, live chain evidence, selected options expression, preferred DTE/moneyness, adversarial review, confidence, ICT thesis, confluences, blockers, entry condition, invalidation, target, post-trade reassessments, orders and exits from the audit trail.

## Testing

```bash
pytest -q
```

The AI decision layer has isolated tests that run without broker credentials. Alpaca-dependent tests require the packages in `requirements.txt` and should be run in the normal project environment.

## Disclaimer

Educational / research software. Paper trading is recommended. Options involve substantial risk of loss. This project does not provide investment advice.

## Autonomous Hypothesis → OOS Research Engine

The system includes `src/autonomous_research.py`, a bounded research scientist that can:

1. formulate a falsifiable hypothesis around an ICT policy;
2. generate a small, bounded candidate policy set;
3. run deterministic backtests on an in-sample period;
4. run a strictly later out-of-sample period;
5. challenge candidates with deterministic statistical gates and an optional adversarial LLM reviewer;
6. promote only candidates that satisfy minimum OOS sample, expectancy, profit factor, drawdown and OOS-decay gates;
7. persist a versioned policy, with hard parameter bounds and an explicit `--commit-policy` opt-in.

The AI may propose or reject hypotheses, but it cannot write arbitrary production parameters. Promotion is a deterministic constitutional gate.

### Run research safely

```bash
python -m src.main --autonomous-research --symbol SPY --start 2025-01-01 --end 2025-06-30
```

This is **dry-run research** by default. To allow a qualifying candidate to update `data/research_policy.json`:

```bash
python -m src.main --autonomous-research --commit-policy --symbol SPY --start 2025-01-01 --end 2025-06-30
```

Policy bounds are intentionally narrow and promotion requires at least 20 OOS trades, positive OOS expectancy, PF ≥ 1.05, acceptable drawdown, adequate train sample and no severe OOS decay. An available LLM challenger can add an additional rejection gate.

> Important: the bundled offline backtester uses synthetic underlying bars and approximated option P&L. It is a research harness, not evidence of live options profitability. Historical option-chain data should be supplied before using research results as performance evidence.
