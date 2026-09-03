# ICT Options Confluence Agent

## One-line pitch
An AI trading agent that reasons over ICT-inspired liquidity, market structure, PD-array and time confluence, chooses **WAIT or TRADE + an options expression**, and sends only risk-approved defined-risk orders to Alpaca.

## What makes it an AI agent
The LLM is no longer a post-hoc veto. It is the **reasoning/orchestration layer**:

1. Observe Alpaca market data.
2. Deterministic ICT engine produces structured evidence.
3. A live Alpaca options-chain analyst builds DTE, moneyness, liquidity, quote, IV and Greeks evidence.
4. Primary AI analyst interprets ICT + chain evidence and proposes `WAIT`/`TRADE` plus an options structure.
5. Adversarial AI challenger attempts to disprove the thesis; failure forces `WAIT`.
6. Deterministic risk governor validates options level, position limits, portfolio risk, delta, quote quality and daily drawdown.
7. Alpaca MCP/SDK execution submits the defined-risk multi-leg order.
8. Post-trade AI monitor reassesses thesis/position state on a controlled interval; deterministic risk/exits remain authoritative.
9. Audit state feeds the next observation cycle.

### AI cannot override the trading constitution
The model cannot flip deterministic bull/bear bias, invent missing ICT evidence, bypass risk gates, select naked short options, or override kill switches. The LLM is the **reasoning layer; code is the authority layer**.

## ICT concepts used
- Sell-side / buy-side liquidity sweeps
- Market Structure Shift (MSS)
- Fair Value Gaps (FVG)
- Order Blocks (OB)
- Premium / Discount
- Dealing Range, equilibrium, octants and Consequent Encroachment
- Kill zones / Silver Bullet / NY Open / London Close
- Opening Range Gap and FPFVG
- Wick/body imbalance
- Seek & Destroy context
- Chain of Custody of Price for target/invalidation context

## Options intelligence
The AI sees live option-chain evidence before selecting a defined-risk structure. It reasons over DTE, moneyness, quote quality, open interest/volume and IV/Greeks when Alpaca supplies them. It does **not** hallucinate strikes or premiums. The deterministic options selector chooses real contracts from the Alpaca chain, while live quote gates reject stale/wide markets.

## Safety
- 0.75% target risk per trade
- 4% max portfolio option risk
- max 4 positions
- max 10 contracts/trade
- portfolio delta cap
- daily loss circuit breaker
- Level 3 options approval required for MLEG
- liquidity / OI / quote-quality gates
- idempotent client order IDs
- deterministic exits and DTE management
- full JSON cycle audit

## Alpaca
The execution boundary supports the official Alpaca MCP server (`place_option_order`) and SDK fallback. Demo configuration should run the MCP path explicitly so the sponsor technology is visible.

## Backtest note
The included backtest is a **synthetic-bar software smoke test**, not historical options performance. It is used to validate signal/exit mechanics and reporting rather than make a profitability claim.

## Judge demo
Recommended flow: show a live SPY/QQQ observation → reveal ICT evidence → show AI thesis and options structure → show deterministic risk gate → show Alpaca MCP execution → show audit record.

## Autonomous research loop
Accepted trades are persisted as falsifiable ICT hypotheses with confirmation/invalidation conditions. The post-trade monitor records observations and produces a learning update against prior research memory. This allows the agent to accumulate structured experience without allowing the LLM to bypass deterministic risk, sizing, contract, or execution controls.
