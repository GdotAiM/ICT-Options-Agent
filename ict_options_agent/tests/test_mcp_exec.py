"""
Unit tests for src/mcp_exec.py — the MCP -> CLI -> SDK fallback chain.

This is the highest-risk file in the codebase: a silent behavior change here
(falls back to SDK when MCP was expected, or drops client_order_id on one
path) won't show up until you're staring at broker logs wondering why an
order type is wrong or why a restart double-filled. Every path is exercised
here with fakes — no real subprocess, no real MCP server, no real network.
"""
import subprocess
import src.mcp_exec as mcp_exec


def _sdk_recorder():
    """Fake sdk_fallback_fn that records exactly what it was called with."""
    calls = []

    def fn(legs, qty, limit_price, client_order_id=None):
        calls.append({
            "legs": legs, "qty": qty,
            "limit_price": limit_price, "client_order_id": client_order_id,
        })
        return {"status": "sdk_called", "id": "sdk-order-1"}

    fn.calls = calls
    return fn


LEGS = [{"symbol": "SPY250919C00500000", "side": "buy"}]


# ---------------- execute_options_order routing ----------------

def test_routes_to_sdk_when_mcp_and_cli_both_disabled(monkeypatch):
    monkeypatch.setattr(mcp_exec, "USE_MCP", False)
    monkeypatch.setattr(mcp_exec, "USE_CLI", False)
    sdk = _sdk_recorder()

    result = mcp_exec.execute_options_order(
        LEGS, qty=2, limit_price=1.25, sdk_fallback_fn=sdk, client_order_id="coid-1"
    )

    assert result["status"] == "sdk_called"
    assert len(sdk.calls) == 1
    assert sdk.calls[0]["client_order_id"] == "coid-1"
    assert sdk.calls[0]["qty"] == 2


def test_raises_when_no_path_enabled_and_no_sdk_fallback():
    import pytest
    mcp_exec.USE_MCP = False
    mcp_exec.USE_CLI = False
    with pytest.raises(RuntimeError):
        mcp_exec.execute_options_order(LEGS, qty=1, limit_price=1.0, sdk_fallback_fn=None)


# ---------------- MCP path ----------------

def test_mcp_missing_package_falls_back_to_sdk(monkeypatch):
    """If the `mcp` package genuinely isn't installed, ImportError must fall
    through to SDK, not raise and abort the trade."""
    monkeypatch.setattr(mcp_exec, "USE_MCP", True)
    monkeypatch.setattr(mcp_exec, "USE_CLI", False)

    def boom(*a, **k):
        if a:
            a[0].close()
        raise ImportError("No module named 'mcp'")
    monkeypatch.setattr(mcp_exec.asyncio, "run", boom)

    sdk = _sdk_recorder()
    result = mcp_exec.execute_options_order(
        LEGS, qty=3, limit_price=2.0, sdk_fallback_fn=sdk, client_order_id="coid-2"
    )

    assert result["status"] == "sdk_called"
    assert sdk.calls[0]["client_order_id"] == "coid-2"


def test_mcp_call_exception_falls_back_to_sdk(monkeypatch):
    """A live MCP session that raises mid-call (server crash, bad schema,
    connection drop) must still fall back to SDK, not lose the order."""
    monkeypatch.setattr(mcp_exec, "USE_MCP", True)
    monkeypatch.setattr(mcp_exec, "USE_CLI", False)

    def boom(*a, **k):
        if a:
            a[0].close()
        raise RuntimeError("MCP server connection reset")
    monkeypatch.setattr(mcp_exec.asyncio, "run", boom)

    sdk = _sdk_recorder()
    result = mcp_exec.execute_options_order(
        LEGS, qty=1, limit_price=None, sdk_fallback_fn=sdk, client_order_id="coid-3"
    )

    assert result["status"] == "sdk_called"
    assert sdk.calls[0]["limit_price"] is None  # market order path preserved


def test_mcp_success_does_not_call_sdk(monkeypatch):
    """When MCP actually succeeds, SDK must NOT also fire (no double order)."""
    monkeypatch.setattr(mcp_exec, "USE_MCP", True)
    monkeypatch.setattr(mcp_exec, "USE_CLI", False)

    def fake_run(coro):
        coro.close()  # avoid 'coroutine was never awaited' warning
        return {"status": "submitted_via_mcp", "result": "ok"}
    monkeypatch.setattr(mcp_exec.asyncio, "run", fake_run)

    sdk = _sdk_recorder()
    result = mcp_exec.execute_options_order(
        LEGS, qty=1, limit_price=1.0, sdk_fallback_fn=sdk, client_order_id="coid-4"
    )

    assert result["status"] == "submitted_via_mcp"
    assert len(sdk.calls) == 0


def test_mcp_no_sdk_fallback_returns_failure_marker_not_exception(monkeypatch):
    """If MCP fails AND there's no SDK fallback, this must return a status
    dict, not raise — callers check result status rather than catching."""
    monkeypatch.setattr(mcp_exec, "USE_MCP", True)
    monkeypatch.setattr(mcp_exec, "USE_CLI", False)

    def boom(*a, **k):
        if a:
            a[0].close()
        raise RuntimeError("no server")
    monkeypatch.setattr(mcp_exec.asyncio, "run", boom)

    result = mcp_exec.execute_options_order(
        LEGS, qty=1, limit_price=1.0, sdk_fallback_fn=None
    )
    assert result["status"] == "mcp_failed_no_sdk_fallback"


def test_legs_for_mcp_maps_buy_sell_to_position_intent():
    legs = [
        {"symbol": "A", "side": "buy"},
        {"symbol": "B", "side": "sell"},
    ]
    out = mcp_exec._legs_for_mcp(legs)
    assert out[0]["position_intent"] == "buy_to_open"
    assert out[1]["position_intent"] == "sell_to_open"
    assert out[0]["ratio_qty"] == "1"


# ---------------- limit_price sign (debit vs credit) ----------------
# Alpaca's mleg convention: positive limit_price = debit (pay), negative =
# credit (receive). A debit spread must reach the broker positive; an iron
# condor's net credit must reach the broker negative. Silently abs()-ing this
# would make every condor order mismatch its own leg composition.

def test_mcp_preserves_positive_limit_price_for_debit_spread(monkeypatch):
    captured = {}

    async def fake_call(legs, qty, limit_price, client_order_id=None):
        captured["limit_price"] = limit_price
        return {"status": "ok"}

    monkeypatch.setattr(mcp_exec, "_call_place_option_order_mcp", fake_call)
    monkeypatch.setattr(mcp_exec, "USE_MCP", True)
    mcp_exec.place_option_mleg_via_mcp(LEGS, qty=1, limit_price=1.25)
    assert captured["limit_price"] == 1.25


def test_mcp_preserves_negative_limit_price_for_credit_condor(monkeypatch):
    captured = {}

    async def fake_call(legs, qty, limit_price, client_order_id=None):
        captured["limit_price"] = limit_price
        return {"status": "ok"}

    monkeypatch.setattr(mcp_exec, "_call_place_option_order_mcp", fake_call)
    monkeypatch.setattr(mcp_exec, "USE_MCP", True)
    mcp_exec.place_option_mleg_via_mcp(LEGS, qty=1, limit_price=-0.85)
    assert captured["limit_price"] == -0.85


# ---------------- CLI path ----------------

def test_cli_binary_missing_falls_back_to_sdk(monkeypatch):
    monkeypatch.setattr(mcp_exec, "USE_MCP", False)
    monkeypatch.setattr(mcp_exec, "USE_CLI", True)

    def raise_not_found(*a, **k):
        raise FileNotFoundError("alpaca: command not found")
    monkeypatch.setattr(subprocess, "run", raise_not_found)

    sdk = _sdk_recorder()
    result = mcp_exec.execute_options_order(
        LEGS, qty=2, limit_price=1.5, sdk_fallback_fn=sdk, client_order_id="coid-5"
    )

    assert result["status"] == "sdk_called"
    assert sdk.calls[0]["client_order_id"] == "coid-5"


def test_cli_nonzero_exit_falls_back_to_sdk(monkeypatch):
    monkeypatch.setattr(mcp_exec, "USE_MCP", False)
    monkeypatch.setattr(mcp_exec, "USE_CLI", True)

    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "unknown flag --client-order-id"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeResult())

    sdk = _sdk_recorder()
    result = mcp_exec.execute_options_order(
        LEGS, qty=1, limit_price=1.0, sdk_fallback_fn=sdk, client_order_id="coid-6"
    )
    assert result["status"] == "sdk_called"


def test_cli_success_does_not_call_sdk(monkeypatch):
    monkeypatch.setattr(mcp_exec, "USE_MCP", False)
    monkeypatch.setattr(mcp_exec, "USE_CLI", True)

    class FakeResult:
        returncode = 0
        stdout = "order submitted"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeResult())

    sdk = _sdk_recorder()
    result = mcp_exec.execute_options_order(
        LEGS, qty=1, limit_price=1.0, sdk_fallback_fn=sdk, client_order_id="coid-7"
    )
    assert result["status"] == "submitted_via_cli"
    assert len(sdk.calls) == 0


def test_cli_includes_client_order_id_in_command(monkeypatch):
    monkeypatch.setattr(mcp_exec, "USE_MCP", False)
    monkeypatch.setattr(mcp_exec, "USE_CLI", True)
    captured = {}

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeResult()

    monkeypatch.setattr(subprocess, "run", fake_run)
    mcp_exec.execute_options_order(
        LEGS, qty=1, limit_price=1.0, sdk_fallback_fn=None, client_order_id="coid-8"
    )
    assert "--client-order-id" in captured["cmd"]
    assert "coid-8" in captured["cmd"]


def test_cli_no_sdk_fallback_raises():
    import pytest
    mcp_exec.USE_MCP = False
    mcp_exec.USE_CLI = True

    def raise_not_found(*a, **k):
        raise FileNotFoundError()
    orig_run = subprocess.run
    subprocess.run = raise_not_found
    try:
        with pytest.raises(RuntimeError):
            mcp_exec.execute_options_order(LEGS, qty=1, limit_price=1.0, sdk_fallback_fn=None)
    finally:
        subprocess.run = orig_run
