"""
Append-only telemetry for the ICT Options Agent.

Two storage backends:
  1. JSONL log file  — survives crashes, no DB dependency, instant writes.
  2. SQLite tables   — queryable, persisted across restarts (opt-in per event).

Every event has:
  - ts_utc      ISO-8601 timestamp
  - event_type  e.g. "llm_call", "quote_eval", "order_filled", "exit_triggered"
  - signal_hash tie-breaker for grouping by trade
  - payload     free-form dict

Use EventLogger singleton from any module — it's thread-safe.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from config import settings

LOG_DIR = settings.AUDIT_DIR.parent / "telemetry"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "events.jsonl"

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventLogger:
    def __init__(self, path: Path = LOG_PATH) -> None:
        self._path = path

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def emit(self, event_type: str, signal_hash: str, payload: Dict[str, Any]) -> None:
        """Append one telemetry event to the JSONL log."""
        record = {
            "ts_utc": _now_iso(),
            "event_type": event_type,
            "signal_hash": signal_hash,
            "payload": payload,
        }
        line = json.dumps(record, default=str) + "\n"
        with _lock:
            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception as e:
                from loguru import logger
                logger.opt_exception(True).debug(f"Telemetry write failed: {e}")

    # ---------------------------------------------------------------
    # LLM
    # ---------------------------------------------------------------

    def llm_call(
        self,
        signal_hash: str,
        *,
        role: str,          # "primary" | "challenger" | "reassess" | "research"
        model: str,
        provider: str,
        latency_ms: float,
        status: str,        # "ok" | "error" | "timeout" | "rate_limited"
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        error_message: Optional[str] = None,
        cost_usd: Optional[float] = None,
    ) -> None:
        self.emit("llm_call", signal_hash, {
            "role": role,
            "model": model,
            "provider": provider,
            "latency_ms": round(latency_ms, 1),
            "status": status,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "error_message": error_message,
            "cost_usd": round(cost_usd, 6) if cost_usd is not None else None,
        })

    # ---------------------------------------------------------------
    # Quote quality
    # ---------------------------------------------------------------

    def quote_eval(
        self,
        signal_hash: str,
        *,
        symbol: str,
        bid: float,
        ask: float,
        mid: float,
        spread_pct: float,
        age_seconds: Optional[float] = None,
        quote_ok: bool,
        reason: str = "",
    ) -> None:
        self.emit("quote_eval", signal_hash, {
            "symbol": symbol,
            "bid": round(bid, 4),
            "ask": round(ask, 4),
            "mid": round(mid, 4),
            "spread_pct": round(spread_pct, 2),
            "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
            "quote_ok": quote_ok,
            "reason": reason,
        })

    # ---------------------------------------------------------------
    # Order execution
    # ---------------------------------------------------------------

    def order_placed(
        self,
        signal_hash: str,
        *,
        client_order_id: str,
        broker_order_id: str,
        path: str,           # "mcp" | "cli" | "sdk"
        legs: list,
        qty: int,
        limit_price: Optional[float],
        latency_ms: float,
        status: str,         # "submitted" | "failed" | "recovered"
        error_message: Optional[str] = None,
    ) -> None:
        self.emit("order_placed", signal_hash, {
            "client_order_id": client_order_id,
            "broker_order_id": broker_order_id,
            "path": path,
            "legs": legs,
            "qty": qty,
            "limit_price": limit_price,
            "latency_ms": round(latency_ms, 1),
            "status": status,
            "error_message": error_message,
        })

    def order_filled(
        self,
        signal_hash: str,
        *,
        client_order_id: str,
        leg_symbol: str,
        side: str,
        qty: int,
        fill_price: float,
        fill_time_utc: str,
    ) -> None:
        self.emit("order_filled", signal_hash, {
            "client_order_id": client_order_id,
            "leg_symbol": leg_symbol,
            "side": side,
            "qty": qty,
            "fill_price": round(fill_price, 4),
            "fill_time_utc": fill_time_utc,
        })

    def order_event(
        self,
        signal_hash: str,
        *,
        event_type: str,
        client_order_id: Optional[str] = None,
        broker_order_id: Optional[str] = None,
        path: Optional[str] = None,
        leg_symbol: Optional[str] = None,
        side: Optional[str] = None,
        qty: Optional[int] = None,
        price: Optional[float] = None,
        latency_ms: Optional[float] = None,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
        trigger: Optional[str] = None,
        pl_pct: Optional[float] = None,
        dte_remaining: Optional[int] = None,
    ) -> None:
        """Unified order event — covers placed / filled_leg / exited."""
        self.emit("order_event", signal_hash, {
            "event_type": event_type,
            "client_order_id": client_order_id,
            "broker_order_id": broker_order_id,
            "path": path,
            "leg_symbol": leg_symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "latency_ms": round(latency_ms, 1) if latency_ms else None,
            "status": status,
            "error_message": error_message,
            "trigger": trigger,
            "pl_pct": round(pl_pct, 2) if pl_pct else None,
            "dte_remaining": dte_remaining,
        })

    # ---------------------------------------------------------------
    # Exit decisions
    # ---------------------------------------------------------------

    def exit_triggered(
        self,
        signal_hash: str,
        *,
        position_symbol: str,
        reason: str,
        trigger: str,      # "profit_target" | "stop_loss" | "max_dte" | "kill_switch" | "eod_flatten" | "ai_reassess_exit"
        pl_pct: float = 0.0,
        dte_remaining: Optional[int] = None,
        equity_at_exit: Optional[float] = None,
    ) -> None:
        self.emit("exit_triggered", signal_hash, {
            "position_symbol": position_symbol,
            "reason": reason,
            "trigger": trigger,
            "pl_pct": round(pl_pct, 2),
            "dte_remaining": dte_remaining,
            "equity_at_exit": equity_at_exit,
        })

    # ---------------------------------------------------------------
    # Market snapshot
    # ---------------------------------------------------------------

    def market_snapshot(
        self,
        signal_hash: str,
        *,
        symbol: str,
        last_price: float,
        underlying_price: float,
    ) -> None:
        self.emit("market_snapshot", signal_hash, {
            "symbol": symbol,
            "last_price": round(last_price, 2),
            "underlying_price": round(underlying_price, 2),
        })

    # ---------------------------------------------------------------
    # Cycle summary (written once per run_cycle)
    # ---------------------------------------------------------------

    def cycle_complete(
        self,
        *,
        equity: float,
        day_start_equity: float,
        halted: bool,
        signals_seen: int,
        trades_fired: int,
        exits_triggered: int,
        llm_calls_made: int,
        llm_failures: int,
        quote_checks: int,
        quote_rejections: int,
    ) -> None:
        self.emit("cycle_complete", "_summary", {
            "equity": round(equity, 2),
            "day_start_equity": round(day_start_equity, 2),
            "halted": halted,
            "signals_seen": signals_seen,
            "trades_fired": trades_fired,
            "exits_triggered": exits_triggered,
            "llm_calls_made": llm_calls_made,
            "llm_failures": llm_failures,
            "quote_checks": quote_checks,
            "quote_rejections": quote_rejections,
        })


# Module-level singleton
logger = EventLogger()
