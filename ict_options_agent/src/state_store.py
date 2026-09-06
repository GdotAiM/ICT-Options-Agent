"""
Local durable state — survives process restarts.

Two jobs:
1. Track every order this agent has submitted (by deterministic client_order_id)
   so a restart never re-enters a signal it already acted on.
2. Track daily starting equity + a halted flag so the kill switch in risk.py
   persists across restarts within the same trading day.

SQLite, single file, no external service — deliberately boring.
"""
from __future__ import annotations
import sqlite3
import hashlib
import json
import threading
from datetime import date
from pathlib import Path
from typing import Optional, Dict, Any, List
from loguru import logger

from config import settings

DB_PATH = Path(getattr(settings, "STATE_DB_PATH", settings.BASE_DIR / "data" / "agent_state.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    with _lock, _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                client_order_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                signal_hash TEXT NOT NULL,
                status TEXT NOT NULL,              -- pending | submitted | failed
                broker_order_id TEXT,
                qty INTEGER,
                limit_price REAL,
                legs_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                trade_date TEXT PRIMARY KEY,
                starting_equity REAL NOT NULL,
                halted INTEGER NOT NULL DEFAULT 0,
                halted_reason TEXT,
                trades_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()
    init_ai_tables()
    logger.info(f"State DB ready at {DB_PATH}")


def make_signal_hash(symbol: str, strategy: str, bias: str, window: str) -> str:
    """Deterministic per (symbol, strategy, bias, kill-zone window, day) — same
    signal firing twice in one window/day hashes identically."""
    raw = f"{symbol}|{strategy}|{bias}|{window}|{date.today().isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def make_client_order_id(signal_hash: str) -> str:
    # Alpaca client_order_id max length is generous but keep it short & safe.
    return f"ict-{signal_hash}"


def get_order_by_client_id(client_order_id: str) -> Optional[Dict[str, Any]]:
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE client_order_id = ?", (client_order_id,)
        ).fetchone()
        return dict(row) if row else None


def has_active_order_for_signal(signal_hash: str) -> bool:
    """True if a pending or submitted order already exists for this exact
    signal (same symbol/strategy/bias/window/day) — blocks duplicate entries
    across restarts."""
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM orders WHERE signal_hash = ? AND status IN ('pending', 'submitted') LIMIT 1",
            (signal_hash,),
        ).fetchone()
        return row is not None


def record_pending_order(
    client_order_id: str,
    symbol: str,
    strategy: str,
    signal_hash: str,
    qty: int,
    limit_price: Optional[float],
    legs_json: str,
) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO orders
               (client_order_id, symbol, strategy, signal_hash, status, qty, limit_price, legs_json)
               VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (client_order_id, symbol, strategy, signal_hash, qty, limit_price, legs_json),
        )
        conn.commit()


def mark_order_submitted(client_order_id: str, broker_order_id: str) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            """UPDATE orders SET status='submitted', broker_order_id=?, updated_at=CURRENT_TIMESTAMP
               WHERE client_order_id=?""",
            (broker_order_id, client_order_id),
        )
        conn.commit()


def mark_order_failed(client_order_id: str) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            """UPDATE orders SET status='failed', updated_at=CURRENT_TIMESTAMP
               WHERE client_order_id=?""",
            (client_order_id,),
        )
        conn.commit()


def list_submitted_orders(limit: int = 50) -> List[Dict[str, Any]]:
    """Recent submitted orders with legs_json — used to reconstruct MLEG closes."""
    with _lock, _conn() as conn:
        rows = conn.execute(
            """SELECT * FROM orders
               WHERE status = 'submitted' AND legs_json IS NOT NULL
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_order_closed(client_order_id: str) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            """UPDATE orders SET status='closed', updated_at=CURRENT_TIMESTAMP
               WHERE client_order_id=?""",
            (client_order_id,),
        )
        conn.commit()


# ---------------- daily stats / kill switch ----------------

def get_or_init_daily_stats(current_equity: float) -> Dict[str, Any]:
    today = date.today().isoformat()
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_stats WHERE trade_date = ?", (today,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO daily_stats (trade_date, starting_equity) VALUES (?, ?)",
                (today, current_equity),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM daily_stats WHERE trade_date = ?", (today,)
            ).fetchone()
        return dict(row)


def set_halted(reason: str) -> None:
    today = date.today().isoformat()
    with _lock, _conn() as conn:
        conn.execute(
            "UPDATE daily_stats SET halted=1, halted_reason=? WHERE trade_date=?",
            (reason, today),
        )
        conn.commit()
    logger.error(f"KILL SWITCH ENGAGED for {today}: {reason}")


def increment_trade_count() -> None:
    today = date.today().isoformat()
    with _lock, _conn() as conn:
        conn.execute(
            "UPDATE daily_stats SET trades_count = trades_count + 1 WHERE trade_date=?",
            (today,),
        )
        conn.commit()

# ---------------- AI position memory / reassessment ----------------

def init_ai_tables() -> None:
    with _lock, _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_position_memory (
                signal_hash TEXT PRIMARY KEY,
                context_json TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_reassessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_hash TEXT NOT NULL,
                verdict TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS research_hypotheses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_hash TEXT NOT NULL,
                hypothesis_json TEXT NOT NULL,
                outcome_json TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS research_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_hash TEXT,
                observation_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        # ── Telemetry tables ─────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                model TEXT NOT NULL,
                provider TEXT NOT NULL,
                latency_ms REAL NOT NULL,
                status TEXT NOT NULL,
                input_tokens INTEGER,
                output_tokens INTEGER,
                error_message TEXT,
                cost_usd REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quote_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_hash TEXT NOT NULL,
                symbol TEXT NOT NULL,
                bid REAL NOT NULL,
                ask REAL NOT NULL,
                mid REAL NOT NULL,
                spread_pct REAL NOT NULL,
                age_seconds REAL,
                quote_ok INTEGER NOT NULL,
                reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS order_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_hash TEXT NOT NULL,
                client_order_id TEXT,
                broker_order_id TEXT,
                event_type TEXT NOT NULL,
                path TEXT,
                leg_symbol TEXT,
                side TEXT,
                qty INTEGER,
                price REAL,
                latency_ms REAL,
                status TEXT,
                error_message TEXT,
                trigger TEXT,
                pl_pct REAL,
                dte_remaining INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def record_ai_context(signal_hash: str, context: Dict[str, Any]) -> None:
    init_ai_tables()
    with _lock, _conn() as conn:
        conn.execute("""INSERT INTO ai_position_memory(signal_hash, context_json)
                       VALUES (?, ?) ON CONFLICT(signal_hash) DO UPDATE SET
                       context_json=excluded.context_json, updated_at=CURRENT_TIMESTAMP""",
                     (signal_hash, json.dumps(context, default=str)))
        conn.commit()


def get_ai_context(signal_hash: str) -> Optional[Dict[str, Any]]:
    init_ai_tables()
    with _lock, _conn() as conn:
        row = conn.execute("SELECT context_json FROM ai_position_memory WHERE signal_hash=?", (signal_hash,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def ai_reassessment_due(signal_hash: str, min_minutes: int = 15) -> bool:
    init_ai_tables()
    with _lock, _conn() as conn:
        row = conn.execute("SELECT created_at FROM ai_reassessments WHERE signal_hash=? ORDER BY id DESC LIMIT 1", (signal_hash,)).fetchone()
    if not row:
        return True
    try:
        from datetime import datetime, timezone
        ts = datetime.fromisoformat(str(row[0]).replace(" ", "T")).replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() >= min_minutes * 60
    except Exception:
        return True


def record_ai_reassessment(signal_hash: str, review: Dict[str, Any]) -> None:
    init_ai_tables()
    with _lock, _conn() as conn:
        verdict = str(review.get("verdict", "UNKNOWN"))
        conn.execute("INSERT INTO ai_reassessments(signal_hash, verdict, payload_json) VALUES (?, ?, ?)",
                     (signal_hash, verdict, json.dumps(review, default=str)))
        conn.commit()


# ---------------- autonomous research / learning memory ----------------

def record_hypothesis(signal_hash: str, hypothesis: Dict[str, Any]) -> int:
    init_ai_tables()
    with _lock, _conn() as conn:
        cur = conn.execute("INSERT INTO research_hypotheses(signal_hash, hypothesis_json) VALUES (?, ?)",
                           (signal_hash, json.dumps(hypothesis, default=str)))
        conn.commit()
        return int(cur.lastrowid)

def record_observation(signal_hash: str, observation: Dict[str, Any]) -> None:
    init_ai_tables()
    with _lock, _conn() as conn:
        conn.execute("INSERT INTO research_observations(signal_hash, observation_json) VALUES (?, ?)",
                     (signal_hash, json.dumps(observation, default=str)))
        conn.commit()

def resolve_hypothesis(signal_hash: str, outcome: Dict[str, Any]) -> None:
    init_ai_tables()
    with _lock, _conn() as conn:
        conn.execute("""UPDATE research_hypotheses
                       SET outcome_json=?, status='resolved', resolved_at=CURRENT_TIMESTAMP
                       WHERE signal_hash=? AND status='open'""",
                     (json.dumps(outcome, default=str), signal_hash))
        conn.commit()

def recent_research_memory(limit: int = 12) -> List[Dict[str, Any]]:
    init_ai_tables()
    with _lock, _conn() as conn:
        rows = conn.execute("""SELECT signal_hash, hypothesis_json, outcome_json, status, created_at, resolved_at
                             FROM research_hypotheses ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
    out=[]
    for r in rows:
        d=dict(r)
        for k in ('hypothesis_json','outcome_json'):
            if d.get(k):
                try: d[k]=json.loads(d[k])
                except Exception: pass
        out.append(d)
    return out



# ── Telemetry accessors ─────────────────────────────────────────────

def record_llm_call(
    signal_hash: str,
    role: str,
    model: str,
    provider: str,
    latency_ms: float,
    status: str,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    error_message: Optional[str] = None,
    cost_usd: Optional[float] = None,
) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            """INSERT INTO llm_calls
               (signal_hash, role, model, provider, latency_ms, status,
                input_tokens, output_tokens, error_message, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (signal_hash, role, model, provider, latency_ms, status,
             input_tokens, output_tokens, error_message, cost_usd),
        )
        conn.commit()


def record_quote_snapshot(
    signal_hash: str,
    symbol: str,
    bid: float,
    ask: float,
    mid: float,
    spread_pct: float,
    age_seconds: Optional[float],
    quote_ok: bool,
    reason: str = "",
) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            """INSERT INTO quote_snapshots
               (signal_hash, symbol, bid, ask, mid, spread_pct,
                age_seconds, quote_ok, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (signal_hash, symbol, bid, ask, mid, spread_pct,
             age_seconds, int(quote_ok), reason),
        )
        conn.commit()


def record_order_event(
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
    with _lock, _conn() as conn:
        conn.execute(
            """INSERT INTO order_events
               (signal_hash, client_order_id, broker_order_id, event_type,
                path, leg_symbol, side, qty, price, latency_ms,
                status, error_message, trigger, pl_pct, dte_remaining)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (signal_hash, client_order_id, broker_order_id, event_type,
             path, leg_symbol, side, qty, price, latency_ms,
             status, error_message, trigger, pl_pct, dte_remaining),
        )
        conn.commit()


def get_telemetry_summary(days: int = 7) -> Dict[str, Any]:
    """Aggregate telemetry for the last N days — useful for dashboards."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM llm_calls WHERE created_at >= ?", (cutoff,)
        ).fetchone()
        llm_total = rows[0]
        rows = conn.execute(
            "SELECT COUNT(*) FROM llm_calls WHERE created_at >= ? AND status='ok'",
            (cutoff,),
        ).fetchone()
        llm_ok = rows[0]
        rows = conn.execute(
            "SELECT COUNT(*) FROM llm_calls WHERE created_at >= ? AND status!='ok'",
            (cutoff,),
        ).fetchone()
        llm_fail = rows[0]
        rows = conn.execute(
            "SELECT AVG(latency_ms), MAX(latency_ms) FROM llm_calls WHERE created_at >= ?",
            (cutoff,),
        ).fetchone()
        avg_latency = rows[0]
        max_latency = rows[1]
        rows = conn.execute(
            "SELECT COUNT(*) FROM order_events WHERE created_at >= ? AND event_type='exited'",
            (cutoff,),
        ).fetchone()
        exits = rows[0]
        rows = conn.execute(
            "SELECT COUNT(*) FROM quote_snapshots WHERE created_at >= ?",
            (cutoff,),
        ).fetchone()
        quote_checks = rows[0]
        rows = conn.execute(
            "SELECT COUNT(*) FROM quote_snapshots WHERE created_at >= ? AND quote_ok=0",
            (cutoff,),
        ).fetchone()
        quote_rejections = rows[0]
    return {
        "period_days": days,
        "llm_calls_total": llm_total,
        "llm_calls_ok": llm_ok,
        "llm_calls_failed": llm_fail,
        "llm_avg_latency_ms": round(avg_latency, 1) if avg_latency else None,
        "llm_max_latency_ms": round(max_latency, 1) if max_latency else None,
        "exits_triggered": exits,
        "quote_checks": quote_checks,
        "quote_rejections": quote_rejections,
    }
