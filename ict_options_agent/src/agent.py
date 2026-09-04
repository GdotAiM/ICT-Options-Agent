"""
ICT Options Agent – live quotes, debit spreads & iron condors.
"""
from typing import Optional, Dict, Any, List
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    OptionLegRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, PositionIntent
from loguru import logger

from config import settings
from src.utils import in_kill_zone
from src.ict_detectors import generate_ict_signal
from src.options_selector import (
    select_bull_call_spread,
    select_bear_put_spread,
    select_iron_condor,
)
from src.risk import (
    calculate_contracts,
    can_open_new_position,
    check_daily_kill_switch,
    should_close_position,
    can_add_risk,
    delta_within_limit,
)
from src.quotes import net_debit_credit, iron_condor_credit
from src.llm_agent import run_ict_agent, run_rth_agent, reassess_open_position
from src.options_chain_agent import build_options_chain_evidence
from src.research_agent import build_hypothesis, resolve_learning
from src.mcp_exec import execute_options_order
from src.audit import write_cycle_audit, summarize_signal_for_audit
from src.status import print_status
from src.utils import now_et
from src import state_store
from src.rth_engine import build_rth_state, is_rth, get_session_phase
import json


# Minimum options trading level required for multi-leg spreads / iron condors.
REQUIRED_OPTIONS_LEVEL = 3


class ICTOptionsAgent:
    def __init__(self, mode: str = "directional"):
        """
        mode: "directional" | "condor" | "auto"
        """
        self.mode = mode
        self.trade_client = TradingClient(
            settings.ALPACA_API_KEY,
            settings.ALPACA_SECRET_KEY,
            paper=settings.ALPACA_PAPER,
        )
        self.data_client = StockHistoricalDataClient(
            settings.ALPACA_API_KEY,
            settings.ALPACA_SECRET_KEY,
        )
        self.equity = self._get_equity()
        self.options_level = self._check_options_level()
        # Per-cycle audit buffers (reset at the start of each run_cycle)
        self._cycle_signals: List[Dict[str, Any]] = []
        self._cycle_orders: List[Dict[str, Any]] = []
        self._cycle_exits: List[Dict[str, Any]] = []
        state_store.init_db()
        daily = state_store.get_or_init_daily_stats(self.equity)
        self.day_starting_equity = daily["starting_equity"]
        self.halted_today = bool(daily["halted"])
        if self.halted_today:
            logger.error(
                f"Kill switch already engaged today ({daily.get('halted_reason')}) — "
                f"no new entries will be placed until tomorrow."
            )
        logger.info(
            f"Agent initialized | Equity: ${self.equity:,.2f} | "
            f"Day start: ${self.day_starting_equity:,.2f} | "
            f"Paper: {settings.ALPACA_PAPER} | Mode: {mode} | "
            f"Options level: {self.options_level}"
        )

    def _check_options_level(self) -> int:
        """
        Confirm the paper account can trade multi-leg options (level 3).
        options_trading_level is the effective level (min of approved + config).
        0=disabled, 1=covered/CSP, 2=long calls/puts, 3=spreads/straddles.
        """
        try:
            acct = self.trade_client.get_account()
            level = getattr(acct, "options_trading_level", None)
            if level is None:
                level = getattr(acct, "options_approved_level", None)
            level = int(level) if level is not None else 0
            if level < REQUIRED_OPTIONS_LEVEL:
                logger.error(
                    f"OPTIONS LEVEL TOO LOW: effective level={level}, "
                    f"required>={REQUIRED_OPTIONS_LEVEL} for MLEG spreads/condors. "
                    f"Enable Level 3 options on the paper account before trading."
                )
            else:
                logger.info(f"Options trading level OK: {level}")
            return level
        except Exception as e:
            logger.warning(f"Could not read options trading level: {e}")
            return 0

    def _get_equity(self) -> float:
        try:
            return float(self.trade_client.get_account().equity)
        except Exception as e:
            logger.error(
                f"Could not fetch equity from Alpaca ({e}) — halting agent. "
                f"Do not trade on phantom equity."
            )
            raise RuntimeError(
                f"Alpaca equity fetch failed: {e}. Set ALPACA_API_KEY and verify "
                "connection before running the agent."
            ) from e

    def get_bars(self, symbol: str, minutes: int = 15, limit: int = 200):
        """
        Fetch bars from Alpaca.  The paper-account data plan only allows
        same-day SIP bars, so we always fetch 1-minute bars and resample
        to the requested timeframe.  This gives us far more history
        (273+ 1m bars vs 23 direct 15m bars) and lets the ICT detectors
        reach their minimum lookback thresholds.
        """
        req_1m = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(1, TimeFrameUnit.Minute),
            limit=limit * minutes,
        )
        df_1m = self.data_client.get_stock_bars(req_1m).df
        if hasattr(df_1m.index, "levels"):
            df_1m = df_1m.xs(symbol)
        if minutes == 1:
            return df_1m
        if len(df_1m) < minutes:
            return df_1m
        df_res = df_1m.resample(f"{minutes}min").agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "volume": "sum"}
        ).dropna()
        return df_res

    def detect_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        # Soft pre-filter – still allow legacy broad window; precise scoring happens inside generate_ict_signal
        from src.utils import time_score, time_context, in_kill_zone
        t_score = time_score()
        if t_score < 0.15:  # very low – skip heavy data fetch
            logger.debug(f"{symbol}: time_score={t_score:.2f} too low, skip")
            return None

        try:
            df_15 = self.get_bars(symbol, minutes=15, limit=150)
            df_5 = self.get_bars(symbol, minutes=5, limit=100)
        except Exception as e:
            logger.error(f"Data fetch failed for {symbol}: {e}")
            return None

        signal = generate_ict_signal(df_15, df_5)
        if signal:
            signal["symbol"] = symbol
            logger.info(
                f"ICT SIGNAL {symbol}: {signal['bias'].upper()} | "
                f"combined={signal.get('combined_score', 0):.2f} | "
                f"{signal['reason']}"
            )
        return signal


    def _place_via_sdk(
        self,
        legs: List[Dict],
        qty: int,
        limit_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ):
        """Working SDK path – always used as fallback (and as default when MCP/CLI off)."""
        option_legs = [
            OptionLegRequest(
                symbol=leg["symbol"],
                side=OrderSide.BUY if leg["side"] == "buy" else OrderSide.SELL,
                ratio_qty=1,
            )
            for leg in legs
        ]
        common = dict(
            qty=qty,
            order_class=OrderClass.MLEG,
            time_in_force=TimeInForce.DAY,
            legs=option_legs,
        )
        if client_order_id:
            common["client_order_id"] = client_order_id

        if limit_price is not None:
            # Preserve sign: Alpaca's mleg convention is positive=debit,
            # negative=credit. Do NOT abs() this — callers (execute_directional
            # / execute_condor) already set the correct sign for the strategy.
            req = LimitOrderRequest(limit_price=round(limit_price, 2), **common)
        else:
            req = MarketOrderRequest(**common)

        try:
            order = self.trade_client.submit_order(req)
        except Exception as e:
            # Duplicate client_order_id means we (or a prior crashed run) already
            # submitted this exact signal — look up the real order instead of
            # treating it as a fresh failure, so a restart never double-fills.
            if client_order_id and "client_order_id" in str(e).lower():
                logger.warning(
                    f"client_order_id {client_order_id} already used — fetching "
                    f"existing order instead of resubmitting"
                )
                try:
                    existing = self.trade_client.get_order_by_client_id(client_order_id)
                    logger.info(f"Recovered existing order: {existing.id}")
                    return existing
                except Exception as e2:
                    logger.error(f"Could not recover existing order: {e2}")
            raise
        logger.info(f"MLEG submitted via SDK: {order.id} | legs={len(legs)} qty={qty}")
        return order

    def _place_mleg(
        self,
        legs: List[Dict],
        qty: int,
        limit_price: Optional[float] = None,
        symbol: str = "",
        strategy: str = "",
        signal_hash: str = "",
    ):
        """
        Idempotent order placement:
        1. Record a 'pending' row in local state BEFORE submitting, keyed by a
           deterministic client_order_id derived from the signal.
        2. Route through mcp_exec (MCP -> CLI -> SDK fallback), passing that
           client_order_id all the way down so even a broker-side retry can't
           double-fill.
        3. Mark the row submitted/failed based on the outcome.
        A restart between steps 1 and 3 just leaves a 'pending' row — the
        pre-submit check in execute() (has_active_order_for_signal) still
        blocks a second attempt at the same signal, and the client_order_id
        would make a genuine broker-side duplicate a safe no-op anyway.
        """
        client_order_id = state_store.make_client_order_id(signal_hash) if signal_hash else None
        if client_order_id:
            state_store.record_pending_order(
                client_order_id=client_order_id,
                symbol=symbol,
                strategy=strategy,
                signal_hash=signal_hash,
                qty=qty,
                limit_price=limit_price,
                legs_json=json.dumps(legs),
            )
        try:
            result = execute_options_order(
                legs=legs,
                qty=qty,
                limit_price=limit_price,
                sdk_fallback_fn=self._place_via_sdk,
                client_order_id=client_order_id,
            )
            if client_order_id:
                broker_id = getattr(result, "id", None) or (
                    result.get("result") if isinstance(result, dict) else None
                )
                state_store.mark_order_submitted(client_order_id, str(broker_id))
                state_store.increment_trade_count()
            self._cycle_orders.append({
                "client_order_id": client_order_id,
                "symbol": symbol,
                "strategy": strategy,
                "qty": qty,
                "limit_price": limit_price,
                "legs": [lg.get("symbol") for lg in legs],
                "result": str(getattr(result, "id", result))[:120],
            })
            return result
        except Exception:
            if client_order_id:
                state_store.mark_order_failed(client_order_id)
            raise


    def execute_directional(self, signal: Dict[str, Any]):
        underlying = signal["symbol"]
        signal_hash = signal.get("signal_hash", "")
        if signal["bias"] == "bull":
            spread = select_bull_call_spread(self.trade_client, underlying, signal)
        else:
            spread = select_bear_put_spread(self.trade_client, underlying, signal)

        if not spread:
            logger.warning(f"No suitable debit spread for {underlying}")
            return

        long_sym = spread["long"].symbol
        short_sym = spread["short"].symbol
        net, long_mid, short_mid, reason = net_debit_credit(long_sym, short_sym)

        if net is None or net <= 0:
            logger.warning(
                f"Skipping {underlying} {spread['type']} — unusable quote "
                f"({reason or f'net={net}'})"
            )
            return
        logger.info(f"Live mid debit: ${net:.2f} (L {long_mid:.2f} / S {short_mid:.2f})")

        max_loss_per = net * 100
        qty = calculate_contracts(self.equity, max_loss_per)
        if qty == 0:
            logger.warning("Zero size after risk calc")
            return
        signal["quote_mids"] = {"long": long_mid, "short": short_mid}
        signal["net_debit"] = net
        signal["qty"] = qty

        try:
            positions = self.trade_client.get_all_positions()
        except Exception:
            positions = []
        ok_risk, risk_reason = can_add_risk(positions, self.equity, max_loss_per * qty)
        if not ok_risk:
            logger.warning(f"Portfolio risk block: {risk_reason}")
            return

        logger.info(
            f"Executing {spread['type']} {underlying} | "
            f"{spread['long_strike']}/{spread['short_strike']} | "
            f"Exp {spread['expiration']} | Debit ~${net:.2f} | Qty {qty}"
        )
        try:
            self._place_mleg(
                spread["legs"], qty, limit_price=net,
                symbol=underlying, strategy=spread["type"], signal_hash=signal_hash,
            )
        except Exception as e:
            logger.error(f"Directional order failed: {e}")

    def execute_condor(self, signal: Dict[str, Any]):
        underlying = signal["symbol"]
        signal_hash = signal.get("signal_hash", "")
        condor = select_iron_condor(self.trade_client, underlying, signal)
        if not condor:
            logger.warning(f"No iron condor found for {underlying}")
            return

        credit, mids, reason = iron_condor_credit(
            condor["long_put"].symbol,
            condor["short_put"].symbol,
            condor["short_call"].symbol,
            condor["long_call"].symbol,
        )
        if credit is None or credit <= 0:
            logger.warning(
                f"Skipping {underlying} iron condor — unusable quote "
                f"({reason or f'credit={credit}'})"
            )
            return
        logger.info(f"Live iron condor credit: ${credit:.2f}")

        wing = abs(condor["strikes"]["short_put"] - condor["strikes"]["long_put"])
        max_loss_per = max(0.01, (wing - credit) * 100)
        qty = calculate_contracts(self.equity, max_loss_per)
        if qty == 0:
            return
        signal["quote_mids"] = mids
        signal["net_credit"] = credit
        signal["qty"] = qty

        try:
            positions = self.trade_client.get_all_positions()
        except Exception:
            positions = []
        ok_risk, risk_reason = can_add_risk(positions, self.equity, max_loss_per * qty)
        if not ok_risk:
            logger.warning(f"Portfolio risk block: {risk_reason}")
            return

        logger.info(
            f"Executing IRON CONDOR {underlying} | {condor['strikes']} | "
            f"Credit ~${credit:.2f} | Qty {qty}"
        )
        try:
            # Alpaca's mleg limit_price convention: positive = debit (pay),
            # negative = credit (receive). `credit` here is a positive
            # magnitude, so it must be negated before it reaches the broker —
            # sending it positive would tell Alpaca this is a debit order,
            # which mismatches the leg composition (sell short strikes, buy
            # wings) and gets rejected or misinterpreted.
            self._place_mleg(
                condor["legs"], qty, limit_price=-credit,
                symbol=underlying, strategy="iron_condor", signal_hash=signal_hash,
            )
        except Exception as e:
            logger.error(f"Condor order failed: {e}")

    def execute(self, signal: Dict[str, Any]):
        # Kill switch — halts all new entries for the rest of the trading day.
        if self.halted_today:
            logger.warning("Kill switch engaged today — skipping new entry")
            self._cycle_signals.append(summarize_signal_for_audit(signal))
            return
        breached, reason = check_daily_kill_switch(self.day_starting_equity, self.equity)
        if breached:
            state_store.set_halted(reason)
            self.halted_today = True
            return

        positions = self.trade_client.get_all_positions()
        if not can_open_new_position(len(positions)):
            logger.warning("Max positions reached")
            signal["blocked"] = "max_positions"
            self._cycle_signals.append(summarize_signal_for_audit(signal))
            return

        ok_delta, delta_reason = delta_within_limit(positions)
        if not ok_delta:
            logger.warning(delta_reason)
            signal["blocked"] = delta_reason
            self._cycle_signals.append(summarize_signal_for_audit(signal))
            return

        # Idempotency guard
        strategy = "condor" if (self.mode == "condor" or signal.get("bias") not in ("bull", "bear")) else "directional"
        window = signal.get("window") or signal.get("kill_zone") or "unknown"
        signal_hash = state_store.make_signal_hash(
            signal["symbol"], strategy, signal.get("bias", "neutral"), window
        )
        signal["signal_hash"] = signal_hash
        if state_store.has_active_order_for_signal(signal_hash):
            logger.info(f"Signal {signal_hash} already has an active order — skipping duplicate")
            return

        # AI is the reasoning/orchestration layer. Give it the live option chain
        # before it chooses the expression; deterministic risk remains authoritative.
        try:
            options_evidence = build_options_chain_evidence(self.trade_client, signal["symbol"], signal)
        except Exception as e:
            options_evidence = {"available": False, "reason": str(e), "underlying": signal["symbol"]}
        signal["options_chain_evidence"] = options_evidence
        decision = run_ict_agent(
            signal,
            require_llm=settings.AI_REQUIRED,
            options_evidence=options_evidence,
        )
        signal["ai_decision"] = decision
        signal["veto"] = decision  # backwards-compatible audit/dashboard field
        if decision.get("decision") != "TRADE" or not decision.get("approve", False):
            logger.warning(
                f"AI chose WAIT ({decision.get('source')}): {decision.get('rationale')}"
            )
            self._cycle_signals.append(summarize_signal_for_audit(signal))
            return
        # Autonomous research layer: turn every accepted setup into a falsifiable
        # experiment and persist it. Research can recommend observations and
        # future hypotheses, but it cannot alter the deterministic risk constitution.
        if settings.RESEARCH_ENABLED:
            try:
                memory = state_store.recent_research_memory(settings.RESEARCH_MEMORY_LIMIT)
                hypothesis = build_hypothesis(signal, decision, memory)
                signal["research_hypothesis"] = hypothesis
                state_store.record_hypothesis(signal_hash, hypothesis)
                logger.info(
                    f"RESEARCH HYPOTHESIS | tag={hypothesis.get('experiment_tag')} | "
                    f"{hypothesis.get('hypothesis')}"
                )
            except Exception as e:
                logger.warning(f"Research hypothesis failed: {e}")

        state_store.record_ai_context(signal_hash, {
            "signal": signal,
            "ai_decision": decision,
            "research_hypothesis": signal.get("research_hypothesis", {}),
        })
        signal["ai_options_dte_target"] = decision.get("preferred_dte", 7)
        signal["ai_options_moneyness"] = decision.get("preferred_moneyness")
        if options_evidence.get("selected_expiration"):
            signal["ai_selected_expiration"] = options_evidence["selected_expiration"]
        logger.info(
            f"AI TRADE decision ({decision.get('source')}) | "
            f"strategy={decision.get('options_strategy')} | "
            f"conf={decision.get('confidence', 0):.2f} | {decision.get('rationale')}"
        )

        # In auto mode, the AI selects the expression while the execution
        # engine still owns actual strikes, quotes, sizing and risk checks.
        ai_strategy = decision.get("options_strategy", "NONE")
        if self.mode == "condor":
            self.execute_condor(signal)
        elif self.mode == "directional":
            self.execute_directional(signal)
        else:
            if ai_strategy == "IRON_CONDOR":
                self.execute_condor(signal)
            elif ai_strategy in {"BULL_CALL_SPREAD", "BEAR_PUT_SPREAD"}:
                self.execute_directional(signal)
            else:
                logger.warning("AI did not select a valid options expression — WAIT")
        self._cycle_signals.append(summarize_signal_for_audit(signal))


    def _close_position_single(self, pos, reason: str) -> bool:
        """Fallback: liquidate one option via close_position."""
        symbol = getattr(pos, "symbol", "")
        qty = getattr(pos, "qty", None)
        try:
            order = self.trade_client.close_position(symbol)
            logger.info(
                f"EXIT single {symbol} qty={qty} reason={reason} | "
                f"close_order={getattr(order, 'id', order)}"
            )
            self._cycle_exits.append({
                "symbol": symbol, "qty": qty, "reason": reason,
                "order_id": str(getattr(order, "id", order)), "style": "single",
            })
            return True
        except Exception as e:
            logger.error(f"Failed to close {symbol}: {e}")
            return False

    def _invert_legs_for_close(self, open_legs: List[Dict]) -> List[Dict]:
        """
        Turn open legs into close legs with opposite side + close intent.
        buy → sell + sell_to_close; sell → buy + buy_to_close.
        """
        close_legs = []
        for leg in open_legs:
            side = (leg.get("side") or "buy").lower()
            if side == "buy":
                close_legs.append({
                    "symbol": leg["symbol"],
                    "side": "sell",
                    "ratio_qty": leg.get("ratio_qty", 1),
                    "position_intent": "sell_to_close",
                    "role": leg.get("role", ""),
                })
            else:
                close_legs.append({
                    "symbol": leg["symbol"],
                    "side": "buy",
                    "ratio_qty": leg.get("ratio_qty", 1),
                    "position_intent": "buy_to_close",
                    "role": leg.get("role", ""),
                })
        return close_legs

    def _place_mleg_close(self, legs: List[Dict], qty: int, reason: str) -> bool:
        """Submit a multi-leg close order (SDK path with PositionIntent)."""
        try:
            option_legs = []
            for leg in legs:
                side = OrderSide.BUY if leg["side"] == "buy" else OrderSide.SELL
                intent_str = leg.get("position_intent", "")
                if intent_str == "buy_to_close":
                    intent = PositionIntent.BUY_TO_CLOSE
                elif intent_str == "sell_to_close":
                    intent = PositionIntent.SELL_TO_CLOSE
                else:
                    intent = (
                        PositionIntent.BUY_TO_CLOSE
                        if side == OrderSide.BUY
                        else PositionIntent.SELL_TO_CLOSE
                    )
                option_legs.append(
                    OptionLegRequest(
                        symbol=leg["symbol"],
                        side=side,
                        ratio_qty=1,
                        position_intent=intent,
                    )
                )
            req = MarketOrderRequest(
                qty=qty,
                order_class=OrderClass.MLEG,
                time_in_force=TimeInForce.DAY,
                legs=option_legs,
            )
            order = self.trade_client.submit_order(req)
            logger.info(
                f"EXIT MLEG qty={qty} legs={len(legs)} reason={reason} | "
                f"order={getattr(order, 'id', order)}"
            )
            self._cycle_exits.append({
                "qty": qty, "reason": reason, "style": "mleg",
                "legs": [lg.get("symbol") for lg in legs],
                "order_id": str(getattr(order, "id", order)),
            })
            return True
        except Exception as e:
            logger.warning(f"MLEG close failed ({e}) — falling back to singles")
            return False

    def _try_grouped_close(self, positions_by_symbol: Dict[str, Any], reason: str) -> set:
        """
        Match open option symbols against stored submitted orders' legs_json.
        When all legs of a past order are still open, close them as one MLEG.
        Returns set of symbols that were successfully closed as a group.
        """
        closed_symbols: set = set()
        try:
            past_orders = state_store.list_submitted_orders(limit=40)
        except Exception as e:
            logger.debug(f"list_submitted_orders failed: {e}")
            return closed_symbols

        open_syms = set(positions_by_symbol.keys())
        for row in past_orders:
            try:
                legs = json.loads(row.get("legs_json") or "[]")
            except Exception:
                continue
            if not legs or len(legs) < 2:
                continue
            leg_syms = [lg.get("symbol") for lg in legs if lg.get("symbol")]
            if not leg_syms or not all(s in open_syms for s in leg_syms):
                continue
            # All legs of this strategy are still open → group close
            qty = int(row.get("qty") or 1)
            close_legs = self._invert_legs_for_close(legs)
            ok = self._place_mleg_close(close_legs, qty, reason)
            if ok:
                for s in leg_syms:
                    closed_symbols.add(s)
                    open_syms.discard(s)
                try:
                    state_store.mark_order_closed(row["client_order_id"])
                except Exception:
                    pass
            # if MLEG failed, leave symbols for single-leg fallback
        return closed_symbols

    def manage_positions(self):
        self.equity = self._get_equity()
        try:
            positions = self.trade_client.get_all_positions()
        except Exception as e:
            logger.error(f"get_all_positions failed: {e}")
            positions = []
        logger.debug(f"Open positions: {len(positions)} | Equity: ${self.equity:,.2f}")

        # AI post-trade feedback loop. The model can request an EXIT, but it
        # cannot bypass deterministic kill-switch, EOD, quote, or broker controls.
        if settings.AI_REASSESS_ENABLED and positions:
            pos_by_symbol = {getattr(p, "symbol", ""): p for p in positions}
            for order in state_store.list_submitted_orders(limit=100):
                sh = order.get("signal_hash")
                if not sh or not state_store.ai_reassessment_due(sh, settings.AI_REASSESS_MINUTES):
                    continue
                context = state_store.get_ai_context(sh) or {}
                symbols = []
                try:
                    symbols = [x.get("symbol") for x in json.loads(order.get("legs_json") or "[]")]
                except Exception:
                    pass
                open_legs = [pos_by_symbol[x] for x in symbols if x in pos_by_symbol]
                if not open_legs:
                    continue
                snapshot = [{
                    "symbol": getattr(p, "symbol", ""),
                    "qty": str(getattr(p, "qty", "")),
                    "side": str(getattr(p, "side", "")),
                    "market_value": getattr(p, "market_value", None),
                    "unrealized_pl": getattr(p, "unrealized_pl", None),
                    "unrealized_plpc": getattr(p, "unrealized_plpc", None),
                } for p in open_legs]
                review = reassess_open_position(context, {
                    "signal_hash": sh, "strategy": order.get("strategy"), "positions": snapshot
                }, require_llm=settings.AI_REQUIRED)
                state_store.record_ai_reassessment(sh, review)
                if settings.RESEARCH_ENABLED:
                    try:
                        learning = resolve_learning(sh, context, {
                            "signal_hash": sh, "strategy": order.get("strategy"),
                            "positions": snapshot,
                        }, review)
                        state_store.record_observation(sh, {
                            "kind": "post_trade_reassessment",
                            "review": review,
                            "learning": learning,
                        })
                    except Exception as e:
                        logger.warning(f"Research learning update failed: {e}")
                self._cycle_signals.append({
                    "type": "ai_post_trade_reassessment", "signal_hash": sh,
                    "verdict": review.get("verdict"), "action": review.get("action"),
                    "reason": review.get("reason"), "source": review.get("source"),
                })
                if str(review.get("action", "HOLD")).upper() == "EXIT":
                    group_map = {getattr(p, "symbol", ""): p for p in open_legs}
                    closed = self._try_grouped_close(group_map, "ai_post_trade_exit")
                    for p in open_legs:
                        sym = getattr(p, "symbol", "")
                        if sym not in closed:
                            self._close_position_single(p, "ai_post_trade_exit")

        # Re-check kill switch every cycle
        if not self.halted_today:
            breached, reason = check_daily_kill_switch(self.day_starting_equity, self.equity)
            if breached:
                state_store.set_halted(reason)
                self.halted_today = True
                logger.error(f"Kill switch engaged: {reason}")
                if settings.FLATTEN_ON_KILL_SWITCH:
                    pos_map = {getattr(p, "symbol", ""): p for p in positions}
                    grouped = self._try_grouped_close(pos_map, f"kill_switch: {reason}")
                    for pos in positions:
                        sym = getattr(pos, "symbol", "")
                        if sym not in grouped:
                            self._close_position_single(pos, f"kill_switch: {reason}")

        # End-of-day flatten (US/Eastern)
        if settings.EOD_FLATTEN and positions:
            et = now_et()
            if (et.hour > settings.EOD_FLATTEN_HOUR) or (
                et.hour == settings.EOD_FLATTEN_HOUR and et.minute >= settings.EOD_FLATTEN_MINUTE
            ):
                logger.info("EOD flatten window — closing all option positions")
                pos_map = {getattr(p, "symbol", ""): p for p in positions}
                grouped = self._try_grouped_close(pos_map, "eod_flatten")
                for pos in positions:
                    sym = getattr(pos, "symbol", "")
                    if sym not in grouped:
                        self._close_position_single(pos, "eod_flatten")
                return

        if not settings.ENABLE_EXITS:
            return

        # Build map of symbols that should exit
        to_exit = {}
        for pos in positions:
            should, why = should_close_position(pos)
            if should:
                to_exit[getattr(pos, "symbol", "")] = (pos, why)

        if not to_exit:
            return

        # Prefer grouped MLEG close when the full original structure is still open
        pos_map = {sym: pair[0] for sym, pair in to_exit.items()}
        sample_reason = next(iter(to_exit.values()))[1]
        grouped_closed = self._try_grouped_close(pos_map, sample_reason)

        for sym, (pos, why) in to_exit.items():
            if sym not in grouped_closed:
                self._close_position_single(pos, why)

    def detect_rth_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        RTH-based signal detection: build a structured market state
        from the RTH session engine instead of requiring MSS-gated patterns.

        Also fetches micro-bar (15s) data from trade ticks to enrich
        the state with higher-density FVGs, sweeps, and displacement.
        """
        if not is_rth():
            logger.debug(f"{symbol}: outside RTH, skip")
            return None

        try:
            df_1m = self.get_bars(symbol, minutes=1, limit=1000)
            df_5m = self.get_bars(symbol, minutes=5, limit=200)
            df_15m = self.get_bars(symbol, minutes=15, limit=200)
        except Exception as e:
            logger.error(f"Data fetch failed for {symbol}: {e}")
            return None

        if len(df_1m) < 5:
            logger.debug(f"{symbol}: insufficient 1m bars ({len(df_1m)})")
            return None

        # Use prior session close as proxy (first bar open if no prior data)
        prior_rth_close = float(df_1m["open"].iloc[0])

        # Fetch micro-bars from trade data (15-min delayed, but enriches patterns)
        micro_bars = None
        try:
            from src.micro_bars import build_micro_bars_multi
            micro_bars = build_micro_bars_multi(
                symbol, client=self.data_client, lookback_minutes=120,
            )
            if micro_bars and (micro_bars.get("15s") is not None):
                logger.debug(
                    f"{symbol}: micro-bars fetched — "
                    f"15s={len(micro_bars['15s'])} bars"
                )
        except Exception as e:
            logger.debug(f"{symbol}: micro-bars unavailable: {e}")

        rth_state = build_rth_state(
            df_1m=df_1m,
            df_5m=df_5m,
            df_15m=df_15m,
            prior_rth_close=prior_rth_close,
            symbol=symbol,
            micro_bars=micro_bars,
        )
        if rth_state:
            micro_info = ""
            if rth_state.get("micro_fvg_count"):
                micro_info = (
                    f" | microFVG={rth_state['micro_fvg_count']}"
                    f" microSweep={rth_state.get('micro_sweep_count', 0)}"
                    f" microBonus={rth_state.get('micro_evidence_bonus', 0):.3f}"
                )
            logger.info(
                f"RTH STATE {symbol}: {rth_state['session']} | "
                f"bias={rth_state['bias']} | score={rth_state.get('combined_score', 0):.2f} | "
                f"{rth_state.get('reason', '')}{micro_info}"
            )
        return rth_state

    def execute_rth(self, rth_state: Dict[str, Any]):
        """Execute using the RTH AI thesis agent."""
        if self.halted_today:
            logger.warning("Kill switch engaged today — skipping new entry")
            self._cycle_signals.append(summarize_signal_for_audit(rth_state))
            return
        breached, reason = check_daily_kill_switch(self.day_starting_equity, self.equity)
        if breached:
            state_store.set_halted(reason)
            self.halted_today = True
            return

        try:
            positions = self.trade_client.get_all_positions()
        except Exception:
            positions = []
        if not can_open_new_position(len(positions)):
            logger.warning("Max positions reached")
            rth_state["blocked"] = "max_positions"
            self._cycle_signals.append(summarize_signal_for_audit(rth_state))
            return

        ok_delta, delta_reason = delta_within_limit(positions)
        if not ok_delta:
            logger.warning(delta_reason)
            rth_state["blocked"] = delta_reason
            self._cycle_signals.append(summarize_signal_for_audit(rth_state))
            return

        # Idempotency
        strategy = "rth"
        window = rth_state.get("session", "unknown")
        signal_hash = state_store.make_signal_hash(
            rth_state.get("symbol", ""), strategy,
            rth_state.get("bias", "neutral"), window,
        )
        rth_state["signal_hash"] = signal_hash
        if state_store.has_active_order_for_signal(signal_hash):
            logger.info(f"Signal {signal_hash} already has an active order — skipping")
            return

        # Build options chain evidence
        try:
            options_evidence = build_options_chain_evidence(
                self.trade_client, rth_state.get("symbol", ""), rth_state,
            )
        except Exception as e:
            options_evidence = {"available": False, "reason": str(e)}
        rth_state["options_chain_evidence"] = options_evidence

        # Run RTH AI agent
        decision = run_rth_agent(
            rth_state,
            require_llm=settings.AI_REQUIRED,
            options_evidence=options_evidence,
        )
        rth_state["ai_decision"] = decision
        rth_state["veto"] = decision

        if decision.get("decision") != "TRADE" or not decision.get("approve", False):
            logger.warning(
                f"AI chose WAIT ({decision.get('source')}): {decision.get('rationale')}"
            )
            self._cycle_signals.append(summarize_signal_for_audit(rth_state))
            return

        # Research hypothesis
        if settings.RESEARCH_ENABLED:
            try:
                memory = state_store.recent_research_memory(settings.RESEARCH_MEMORY_LIMIT)
                hypothesis = build_hypothesis(rth_state, decision, memory)
                rth_state["research_hypothesis"] = hypothesis
                state_store.record_hypothesis(signal_hash, hypothesis)
                logger.info(
                    f"RESEARCH HYPOTHESIS | tag={hypothesis.get('experiment_tag')} | "
                    f"{hypothesis.get('hypothesis')}"
                )
            except Exception as e:
                logger.warning(f"Research hypothesis failed: {e}")

        state_store.record_ai_context(signal_hash, {
            "signal": rth_state,
            "ai_decision": decision,
            "research_hypothesis": rth_state.get("research_hypothesis", {}),
        })
        rth_state["ai_options_dte_target"] = decision.get("preferred_dte", 7)
        rth_state["ai_options_moneyness"] = decision.get("preferred_moneyness")
        if options_evidence.get("selected_expiration"):
            rth_state["ai_selected_expiration"] = options_evidence["selected_expiration"]
        logger.info(
            f"AI TRADE decision ({decision.get('source')}) | "
            f"thesis={decision.get('thesis_model')} | "
            f"strategy={decision.get('options_strategy')} | "
            f"conf={decision.get('confidence', 0):.2f} | {decision.get('rationale')}"
        )

        # Execute the options expression
        ai_strategy = decision.get("options_strategy", "NONE")
        # Convert RTH state to a signal-compatible dict for the execution methods
        exec_signal = {
            "symbol": rth_state.get("symbol", ""),
            "bias": decision.get("direction", rth_state.get("bias", "neutral")),
            "signal_hash": signal_hash,
            "underlying_price": rth_state.get("last_price", 0),
        }
        if ai_strategy == "IRON_CONDOR":
            self.execute_condor(exec_signal)
        elif ai_strategy in {"BULL_CALL_SPREAD", "BEAR_PUT_SPREAD"}:
            self.execute_directional(exec_signal)
        else:
            logger.warning("AI did not select a valid options expression — WAIT")
        self._cycle_signals.append(summarize_signal_for_audit(rth_state))

    def run_cycle(self):
        self._cycle_signals = []
        self._cycle_orders = []
        self._cycle_exits = []

        # Guard: refuse new entries if options level is insufficient
        if self.options_level < REQUIRED_OPTIONS_LEVEL:
            logger.error(
                f"Skipping entries — options level {self.options_level} "
                f"< required {REQUIRED_OPTIONS_LEVEL}"
            )
            self.manage_positions()  # still allow exits
            self._write_audit_and_status()
            return

        self.manage_positions()
        if self.halted_today:
            logger.warning("Kill switch engaged — skipping this cycle's signal scan")
            self._write_audit_and_status()
            return

        # RTH engine path: use the session-based market state
        # instead of the old MSS-gated detector
        for symbol in settings.UNDERLYINGS:
            rth_state = self.detect_rth_signal(symbol)
            if rth_state:
                self.execute_rth(rth_state)
        self._write_audit_and_status()

    def _write_audit_and_status(self):
        """Persist cycle audit JSON and print a terminal status snapshot."""
        try:
            positions = self.trade_client.get_all_positions()
        except Exception:
            positions = []
        pos_snap = []
        for p in positions:
            pos_snap.append({
                "symbol": getattr(p, "symbol", ""),
                "qty": str(getattr(p, "qty", "")),
                "side": str(getattr(p, "side", "")),
                "unrealized_plpc": getattr(p, "unrealized_plpc", None),
                "market_value": getattr(p, "market_value", None),
            })
        try:
            write_cycle_audit(
                mode=self.mode,
                equity=self.equity,
                day_start=self.day_starting_equity,
                halted=self.halted_today,
                options_level=self.options_level,
                signals=self._cycle_signals,
                orders=self._cycle_orders,
                exits=self._cycle_exits,
                positions_snapshot=pos_snap,
            )
        except Exception as e:
            logger.warning(f"Audit write failed: {e}")
        try:
            print_status(
                equity=self.equity,
                day_start=self.day_starting_equity,
                halted=self.halted_today,
                options_level=self.options_level,
                positions=positions,
                mode=self.mode,
            )
        except Exception as e:
            logger.debug(f"Status print failed: {e}")
