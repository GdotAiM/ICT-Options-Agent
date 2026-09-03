"""
Simple ICT signal backtester on historical stock bars.
Options P&L is approximated (debit/credit * move) for speed; 
for higher fidelity replace with historical option chains.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from loguru import logger

from src.ict_detectors import generate_ict_signal, detect_swings, detect_fvg, premium_discount
from config import settings


def load_or_fetch_bars(symbol: str, start: str, end: str, timeframe_minutes: int = 15) -> pd.DataFrame:
    """
    Placeholder: in production use Alpaca historical bars or a CSV cache.
    For offline demo we generate synthetic data with some structure.
    """
    # Synthetic path for immediate usability without keys
    idx = pd.date_range(start=start, end=end, freq=f"{timeframe_minutes}min")
    # Keep only market hours roughly
    idx = idx[(idx.hour >= 9) & (idx.hour < 16)]
    n = len(idx)
    if n == 0:
        return pd.DataFrame()

    np.random.seed(hash(symbol) % 2**32)
    # Random walk + occasional jumps to create sweeps
    rets = np.random.randn(n) * 0.0015
    # Inject a few larger moves
    for _ in range(max(3, n // 200)):
        i = np.random.randint(20, n - 20)
        rets[i : i + 5] += np.random.choice([-1, 1]) * 0.008
    close = 100 * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(np.random.randn(n) * 0.002))
    low = close * (1 - np.abs(np.random.randn(n) * 0.002))
    open_ = close + np.random.randn(n) * 0.1
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=idx,
    )
    return df


def run_backtest(
    symbol: str = "SPY",
    start: str = "2025-01-01",
    end: str = "2025-06-30",
    risk_pct: float = 0.0075,
    initial_equity: float = 100_000.0,
    approx_debit: float = 1.20,
    target_r: float = 1.8,
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Walk-forward on 15m bars.
    On each bar, generate ICT signal using trailing window.
    Simulate entry at next bar open, exit at target or stop or time.
    Options P&L approximated as: win → +target_r * risk, loss → -1R.
    """
    df = load_or_fetch_bars(symbol, start, end, 15)
    if df.empty or len(df) < 100:
        logger.warning("Insufficient data for backtest")
        return {}

    equity = initial_equity
    trades: List[Dict] = []
    position = None
    lookback = 80

    for i in range(lookback, len(df) - 5):
        window_15 = df.iloc[i - lookback : i + 1].copy()
        # Use same window as proxy for 5m (simplification)
        window_5 = window_15.copy()

        if position is not None:
            # Manage open trade
            bar = df.iloc[i]
            if position["bias"] == "bull":
                hit_target = bar["high"] >= position["target"]
                hit_stop = bar["low"] <= position["stop"]
            else:
                hit_target = bar["low"] <= position["target"]
                hit_stop = bar["high"] >= position["stop"]

            if hit_target or hit_stop or (i - position["entry_i"]) > 20:
                r_mult = target_r if hit_target else (-1.0 if hit_stop else 0.0)
                pnl = position["risk_dollars"] * r_mult
                equity += pnl
                trades.append(
                    {
                        **position,
                        "exit_i": i,
                        "exit_price": float(bar["close"]),
                        "r_mult": r_mult,
                        "pnl": pnl,
                        "equity_after": equity,
                    }
                )
                position = None
            continue

        signal = generate_ict_signal(window_15, window_5, as_of=df.index[i])
        if not signal:
            continue

        # Research policies are bounded filters over deterministic ICT evidence.
        # They never alter the underlying signal or risk engine.
        policy = policy or {}
        if float(signal.get("combined_score", 0)) < float(policy.get("min_combined_score", 0.0)):
            continue
        if float(signal.get("time_score", 0)) < float(policy.get("min_time_score", 0.0)):
            continue
        if policy.get("require_snd_clear") and signal.get("snd_warning"):
            continue

        # Size
        risk_dollars = equity * risk_pct
        stop_dist = abs(signal["underlying_price"] - signal["stop"])
        if stop_dist <= 0:
            continue

        position = {
            "symbol": symbol,
            "bias": signal["bias"],
            "entry_i": i,
            "entry_price": float(df.iloc[i]["close"]),
            "stop": signal["stop"],
            "target": signal["target"],
            "risk_dollars": risk_dollars,
            "reason": signal["reason"],
            "approx_debit": approx_debit,
        }

    # Summary
    if not trades:
        return {"trades": 0, "final_equity": equity, "return_pct": 0.0}

    pnls = [t["pnl"] for t in trades]
    peak = initial_equity
    max_drawdown = 0.0
    curve = initial_equity
    for p in pnls:
        curve += p
        peak = max(peak, curve)
        if peak:
            max_drawdown = max(max_drawdown, (peak - curve) / peak)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total_pnl = sum(pnls)
    win_rate = len(wins) / len(trades) if trades else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

    return {
        "symbol": symbol,
        "start": start,
        "end": end,
        "trades": len(trades),
        "win_rate": round(win_rate, 3),
        "total_pnl": round(total_pnl, 2),
        "final_equity": round(equity, 2),
        "return_pct": round((equity / initial_equity - 1) * 100, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf",
        "expectancy_r": round(float(np.mean([t["r_mult"] for t in trades])), 3),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "policy": policy or {},
        "trade_log": trades[-20:],  # last 20 for inspection
    }


if __name__ == "__main__":
    from src.utils import setup_logging
    setup_logging()
    result = run_backtest("SPY", "2025-01-01", "2025-06-30")
    logger.info(f"Backtest result: {result}")
