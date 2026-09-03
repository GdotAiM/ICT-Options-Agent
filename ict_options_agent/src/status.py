"""
Terminal status view + helpers for the optional Streamlit dashboard.

Prints a compact snapshot: equity, kill-switch, open positions, recent
audit signals/vetoes. Safe to call without a live broker (falls back).
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from loguru import logger
from config import settings


def _load_latest_audit() -> Optional[Dict[str, Any]]:
    audit_dir = Path(settings.AUDIT_DIR)
    if not audit_dir.exists():
        return None
    files = sorted(audit_dir.glob("cycle_*.json"), reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text())
    except Exception:
        return None


def format_status(
    equity: float = 0,
    day_start: float = 0,
    halted: bool = False,
    halted_reason: str = "",
    options_level: int = 0,
    positions: Optional[List[Any]] = None,
    mode: str = "",
) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("ICT OPTIONS AGENT — STATUS")
    lines.append("=" * 60)
    lines.append(f"Time (local): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Mode: {mode or 'n/a'} | Options level: {options_level}")
    lines.append(f"Equity: ${equity:,.2f} | Day start: ${day_start:,.2f}")
    if day_start > 0:
        dd = (equity - day_start) / day_start
        lines.append(f"Day P&L: {dd:+.2%}")
    if halted:
        lines.append(f"KILL SWITCH: ON — {halted_reason or 'engaged'}")
    else:
        lines.append("Kill switch: off")

    positions = positions or []
    lines.append(f"\nOpen positions: {len(positions)}")
    for p in positions:
        sym = getattr(p, "symbol", p.get("symbol") if isinstance(p, dict) else "?")
        qty = getattr(p, "qty", p.get("qty") if isinstance(p, dict) else "?")
        plpc = getattr(p, "unrealized_plpc", None)
        if plpc is None and isinstance(p, dict):
            plpc = p.get("unrealized_plpc")
        try:
            plpc_s = f"{float(plpc):+.1%}" if plpc is not None else "n/a"
        except (TypeError, ValueError):
            plpc_s = "n/a"
        lines.append(f"  {sym}  qty={qty}  uPL={plpc_s}")

    audit = _load_latest_audit()
    if audit:
        lines.append(f"\nLatest audit: {audit.get('ts_utc', '')}")
        for s in (audit.get("signals") or [])[:8]:
            veto = s.get("ai_decision") or s.get("veto") or {}
            lines.append(
                f"  {s.get('symbol')} {s.get('bias')} score={s.get('combined_score')} "
                f"AI={veto.get('decision')} strategy={veto.get('options_strategy')} conf={veto.get('confidence', 0):.2f} ({veto.get('source')}: {veto.get('rationale', '')[:45]})"
            )
        if audit.get("orders"):
            lines.append(f"  Orders this cycle: {len(audit['orders'])}")
        if audit.get("exits"):
            lines.append(f"  Exits this cycle: {len(audit['exits'])}")
    else:
        lines.append("\nNo audit artifacts yet.")

    lines.append("=" * 60)
    return "\n".join(lines)


def print_status(**kwargs) -> None:
    text = format_status(**kwargs)
    print(text)
    logger.info("Status snapshot printed")
