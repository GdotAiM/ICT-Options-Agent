from src.llm_agent import run_ict_agent, reassess_open_position


def base_signal(**overrides):
    s = {
        "symbol": "SPY",
        "bias": "bull",
        "underlying_price": 640.0,
        "entry_zone": 638.5,
        "stop": 636.0,
        "target": 646.0,
        "sweep_level": 637.0,
        "pd_zone": "discount",
        "combined_score": 0.82,
        "time_score": 0.9,
        "active_windows": ["silver_bullet"],
        "reason": "ssl_sweep + MSS + discount FVG + time[silver_bullet]",
        "snd_warning": False,
    }
    s.update(overrides)
    return s


def test_fallback_is_an_ict_trade_decision(monkeypatch):
    """When the LLM is unavailable, the deterministic fallback should
    produce a TRADE decision for a high-confluence signal."""
    import src.llm_agent as mod
    monkeypatch.setattr(mod, "_call_openai", lambda signal, options_evidence=None: None)
    monkeypatch.setattr(mod, "_challenge_openai", lambda *a, **kw: {"verdict": "PASS", "reason": "ok"})
    d = run_ict_agent(base_signal())
    assert d["decision"] == "TRADE"
    assert d["direction"] == "bull"
    assert d["options_strategy"] == "BULL_CALL_SPREAD"
    assert "liquidity sweep" in d["required_confluences"]


def test_seek_destroy_forces_wait(monkeypatch):
    """When the LLM is unavailable, the deterministic fallback should
    produce WAIT when snd_warning is True."""
    import src.llm_agent as mod
    monkeypatch.setattr(mod, "_call_openai", lambda signal, options_evidence=None: None)
    monkeypatch.setattr(mod, "_challenge_openai", lambda *a, **kw: {"verdict": "PASS", "reason": "ok"})
    d = run_ict_agent(base_signal(snd_warning=True))
    assert d["decision"] == "WAIT"
    assert d["approve"] is False


def test_bear_signal_maps_to_put_spread():
    d = run_ict_agent(base_signal(bias="bear", pd_zone="premium"))
    assert d["direction"] == "bear"
    assert d["options_strategy"] == "BEAR_PUT_SPREAD"


def test_low_confluence_waits():
    d = run_ict_agent(base_signal(combined_score=0.40))
    assert d["decision"] == "WAIT"


def test_ai_required_fails_closed(monkeypatch):
    import src.llm_agent as mod
    monkeypatch.setattr(mod, "_call_openai", lambda signal: None)
    d = mod.run_ict_agent(base_signal(), require_llm=True)
    assert d["decision"] == "WAIT"
    assert d["source"] == "ai_unavailable_fail_closed"


def test_ai_challenger_failure_forces_wait(monkeypatch):
    import src.llm_agent as mod
    monkeypatch.setattr(mod, "_call_openai", lambda signal, options_evidence=None: {
        "decision": "TRADE", "approve": True, "direction": "bull",
        "options_strategy": "BULL_CALL_SPREAD", "confidence": 0.9,
    })
    monkeypatch.setattr(mod, "_challenge_openai", lambda *args, **kwargs: {
        "verdict": "FAIL", "reason": "target liquidity is not supported", "contradictions": ["no clean path"]
    })
    d = mod.run_ict_agent(base_signal())
    assert d["decision"] == "WAIT"
    assert d["adversarial_review"]["verdict"] == "FAIL"


def test_challenger_unavailable_fails_closed_even_without_ai_required(monkeypatch):
    """An unavailable adversarial challenger must never be treated as a pass,
    even when AI_REQUIRED/require_llm is left at its default (False)."""
    import src.llm_agent as mod
    monkeypatch.setattr(mod, "_call_openai", lambda signal, options_evidence=None: {
        "decision": "TRADE", "approve": True, "direction": "bull",
        "options_strategy": "BULL_CALL_SPREAD", "confidence": 0.9,
    })
    monkeypatch.setattr(mod, "_challenge_openai", lambda *args, **kwargs: None)
    d = mod.run_ict_agent(base_signal(), require_llm=False)
    assert d["decision"] == "WAIT"
    assert d["approve"] is False
    assert d["adversarial_review"]["verdict"] == "UNAVAILABLE"


def test_reassess_reports_unavailable_consistently_regardless_of_require_llm(monkeypatch):
    """The post-trade monitor's verdict must say UNAVAILABLE whenever it
    can't run, whether or not AI_REQUIRED/require_llm is set — action stays
    HOLD either way since deterministic exits remain authoritative."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    for flag in (False, True):
        d = reassess_open_position({}, {}, require_llm=flag)
        assert d["verdict"] == "UNAVAILABLE"
        assert d["action"] == "HOLD"


def test_ai_receives_options_chain_and_can_choose_dte(monkeypatch):
    import src.llm_agent as mod
    captured = {}
    def fake(signal, options_evidence=None):
        captured["chain"] = options_evidence
        return {
            "decision": "TRADE", "approve": True, "direction": "bull",
            "options_strategy": "BULL_CALL_SPREAD", "confidence": 0.88,
            "preferred_dte": 9, "preferred_moneyness": "slightly_ITM",
        }
    monkeypatch.setattr(mod, "_call_openai", fake)
    monkeypatch.setattr(mod, "_challenge_openai", lambda *args, **kwargs: {"verdict": "PASS", "reason": "coherent"})
    chain = {"available": True, "selected_expiration": "2026-09-11", "dte": 9, "calls": [{"strike": 640, "mid": 5.2, "greeks": {"delta": 0.55}}]}
    d = mod.run_ict_agent(base_signal(), options_evidence=chain)
    assert captured["chain"]["dte"] == 9
    assert d["preferred_dte"] == 9
