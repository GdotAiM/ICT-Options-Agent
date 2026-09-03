"""Basic unit tests for ICT detectors (no live API needed)."""
import pandas as pd
import numpy as np
from src.ict_detectors import detect_swings, detect_fvg, premium_discount, generate_ict_signal


def _make_sample_df(n=100):
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(n) * 0.3)
    high = close + np.random.rand(n) * 0.5
    low = close - np.random.rand(n) * 0.5
    open_ = close + np.random.randn(n) * 0.1
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close})


def test_detect_swings():
    df = _make_sample_df()
    out = detect_swings(df)
    assert "swing_high" in out.columns
    assert "swing_low" in out.columns


def test_detect_fvg():
    df = _make_sample_df()
    out = detect_fvg(df)
    assert "bull_fvg_bot" in out.columns


def test_premium_discount():
    df = _make_sample_df()
    info = premium_discount(df)
    assert info["zone"] in ("premium", "discount")


def test_generate_signal_runs():
    df15 = _make_sample_df(120)
    df5 = _make_sample_df(80)
    # May or may not produce a signal on random data – just ensure no crash
    _ = generate_ict_signal(df15, df5)
