"""
Per-cycle decision audit trail.

Writes one JSON artifact per cycle under logs/audit/ so judges (and you)
can reconstruct every signal, score component, quote mid, veto, and order id.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger
from config import settings


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_cycle_audit(
    *,
    mode: str,
    equity: float,
    halted: bool,
    options_level: int,
    signals: List[Dict[str, Any]],
    orders: List[Dict[str, Any]],
    exits: List[Dict[str, Any]],
    positions_snapshot: List[Dict[str, Any]],
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    """
    Persist a single cycle's full decision trail.
    Returns the path of the written JSON file.
    """
    payload = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "equity": equity,
        "halted": halted,
        "options_level": options_level,
        "signals": signals,
        "orders": orders,
        "exits": exits,
        "positions": positions_snapshot,
        "extra": extra or {},
    }
    path = Path(settings.AUDIT_DIR) / f"cycle_{_ts()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    logger.info(f"Audit trail written: {path}")
    return path


def summarize_signal_for_audit(signal: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the audit record compact but complete for scoring/veto review."""
    keys = [
        "symbol", "bias", "reason", "combined_score", "time_score",
        "active_windows", "snd_warning", "chain_of_custody",
        "underlying_price", "entry_zone", "signal_hash", "veto", "ai_decision",
        "quote_mids", "net_debit", "net_credit", "qty", "client_order_id",
        "score_components",
    ]
    out = {k: signal.get(k) for k in keys if k in signal or signal.get(k) is not None}
    # Always include score breakdown if present
    for k, v in signal.items():
        if k.startswith("score_") or k.endswith("_score"):
            out[k] = v
    return out
