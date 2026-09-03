"""Critical-safety regression tests for agent.py risk gates.

These exercise the paths flagged by the Judge 3 safety audit:
- _get_equity must raise on API failure (not silently return $100k)
- Kill-switch flatten must actually close positions when engaged
- Max-positions guard must block entry even with valid ICT signal
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — build a minimal agent proxy without calling the real __init__
# ---------------------------------------------------------------------------

def _make_proxy_agent():
    """Return a plain object with the methods/attrs we need from ICTOptionsAgent,
    without invoking the real constructor (which requires API keys)."""
    from src.agent import ICTOptionsAgent
    agent = object.__new__(ICTOptionsAgent)
    agent.mode = "auto"
    agent.trade_client = MagicMock()
    agent.data_client = MagicMock()
    agent.equity = 100_000.0
    agent.day_starting_equity = 100_000.0
    agent.options_level = 3
    agent.halted_today = False
    agent._cycle_signals = []
    agent._cycle_orders = []
    agent._cycle_exits = []
    return agent


# ---------------------------------------------------------------------------
# _get_equity: must raise on API failure, not return phantom equity
# ---------------------------------------------------------------------------

def test_get_equity_raises_on_api_failure():
    """_get_equity must NOT fall back to $100k — that enables blind trading.

    Regression test for Judge 3 finding: returning a hardcoded equity on
    API failure lets the agent size and submit orders against phantom capital.
    """
    agent = _make_proxy_agent()
    agent.trade_client.get_account.side_effect = ConnectionError("host unreachable")
    with pytest.raises(RuntimeError, match="Alpaca equity fetch failed"):
        agent._get_equity()


def test_get_equity_returns_real_value_on_success():
    agent = _make_proxy_agent()
    agent.trade_client.get_account.return_value = SimpleNamespace(equity=250_000.50)
    assert agent._get_equity() == 250_000.50


# ---------------------------------------------------------------------------
# Kill-switch flatten path
# ---------------------------------------------------------------------------

def test_kill_switch_flattens_positions_when_enabled(monkeypatch):
    """When FLATTEN_ON_KILL_SWITCH is true and the switch trips mid-cycle,
    open option positions must be closed."""
    from config import settings

    monkeypatch.setattr(settings, "FLATTEN_ON_KILL_SWITCH", True)
    monkeypatch.setattr(settings, "EOD_FLATTEN", False)
    monkeypatch.setattr(settings, "ENABLE_EXITS", False)

    agent = _make_proxy_agent()
    agent.halted_today = False

    # Simulate equity drop that breaches the 3% kill switch
    agent.equity = 96_000.0  # 4% drawdown

    # One open option position
    opt_pos = SimpleNamespace(
        symbol="SPY250919C00500000",
        qty="2",
        side="long",
        asset_class="us_option",
        delta=0.45,
    )
    agent.trade_client.get_all_positions.return_value = [opt_pos]

    with patch.object(agent, "_try_grouped_close") as mock_grouped, \
         patch.object(agent, "_close_position_single") as mock_single:
        mock_grouped.return_value = set()  # grouped close not attempted
        agent.manage_positions()

    # Kill switch should have tripped and flatten the position
    assert agent.halted_today is True
    assert mock_single.call_count == 1
    args = mock_single.call_args
    assert args[0][0] is opt_pos
    assert "kill_switch" in args[0][1]


def test_kill_switch_no_flatten_when_disabled(monkeypatch):
    """When FLATTEN_ON_KILL_SWITCH is false (legacy behaviour), the switch
    still halts new entries but does NOT force-close open positions."""
    from config import settings

    monkeypatch.setattr(settings, "FLATTEN_ON_KILL_SWITCH", False)
    monkeypatch.setattr(settings, "EOD_FLATTEN", False)
    monkeypatch.setattr(settings, "ENABLE_EXITS", False)

    agent = _make_proxy_agent()
    agent.halted_today = False
    agent.equity = 96_000.0  # 4% drawdown

    opt_pos = SimpleNamespace(
        symbol="SPY250919C00500000",
        qty="2",
        side="long",
        asset_class="us_option",
        delta=0.45,
    )
    agent.trade_client.get_all_positions.return_value = [opt_pos]

    with patch.object(agent, "_try_grouped_close") as mock_grouped, \
         patch.object(agent, "_close_position_single") as mock_single:
        mock_grouped.return_value = set()
        agent.manage_positions()

    # No close called — only new entries are blocked
    mock_single.assert_not_called()
    assert agent.halted_today is True


# ---------------------------------------------------------------------------
# Max-positions guard blocks entry
# ---------------------------------------------------------------------------

def test_execute_blocks_when_max_positions_reached():
    """execute() must refuse new entries when the position cap is reached,
    even if the ICT signal and AI decision are both TRADE."""
    from src.agent import ICTOptionsAgent

    agent = _make_proxy_agent()
    agent.halted_today = False

    # 4 positions already open (MAX_POSITIONS default)
    positions = [SimpleNamespace(symbol=f"SPY{i}") for i in range(4)]
    agent.trade_client.get_all_positions.return_value = positions

    signal = {
        "symbol": "SPY",
        "bias": "bull",
        "combined_score": 0.85,
        "time_score": 0.9,
        "window": "silver_bullet",
    }

    with patch.object(agent, "execute_directional") as mock_dir, \
         patch.object(agent, "execute_condor") as mock_condor, \
         patch("src.agent.run_ict_agent") as mock_ai:
        mock_ai.return_value = {"decision": "TRADE", "approve": True, "options_strategy": "BULL_CALL_SPREAD"}
        agent.execute(signal)

    # AI should never have been called — risk gate fires first
    mock_ai.assert_not_called()
    mock_dir.assert_not_called()
    mock_condor.assert_not_called()


# ---------------------------------------------------------------------------
# Options-level guard blocks entry
# ---------------------------------------------------------------------------

def test_run_cycle_skips_entries_when_options_level_insufficient():
    """run_cycle() must skip signal detection entirely when options level < 3,
    but still call manage_positions() so existing positions can be exited."""
    agent = _make_proxy_agent()
    agent.options_level = 2  # below REQUIRED_OPTIONS_LEVEL = 3

    with patch.object(agent, "detect_signal") as mock_detect, \
         patch.object(agent, "manage_positions") as mock_manage:
        agent.run_cycle()

    mock_detect.assert_not_called()
    mock_manage.assert_called_once()
