from src.research_agent import build_hypothesis, resolve_learning
from src import state_store


def signal():
    return {
        "symbol": "SPY", "bias": "bull", "combined_score": 0.82,
        "time_score": 0.9, "stop": 636, "target": 646,
        "reason": "SSL sweep + MSS + discount FVG"
    }


def test_research_fallback_is_falsifiable():
    d = build_hypothesis(signal(), {"decision": "TRADE"}, [])
    assert d["hypothesis"]
    assert d["confirmation_conditions"]
    assert d["invalidation_conditions"]
    assert d["next_observations"]


def test_research_memory_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "DB_PATH", tmp_path / "state.db")
    state_store.init_db()
    state_store.record_hypothesis("abc", {"hypothesis": "test"})
    rows = state_store.recent_research_memory()
    assert rows[0]["signal_hash"] == "abc"
    state_store.record_observation("abc", {"event": "mss_intact"})
    state_store.resolve_hypothesis("abc", {"outcome": "WIN"})
    assert state_store.recent_research_memory()[0]["status"] == "resolved"


def test_learning_fallback_does_not_claim_edge():
    d = resolve_learning("abc", {"hypothesis": {"hypothesis": "test"}}, {"unrealized_pl": 0}, {})
    assert d["outcome"] == "OPEN"
    assert "insufficient" in d["lesson"].lower()
