from src.autonomous_research import _bounded, propose_hypotheses, deterministic_challenge


def test_policy_bounds_are_hard():
    p = _bounded({"min_combined_score": 2, "min_time_score": -1, "require_snd_clear": 1})
    assert p["min_combined_score"] == 0.95
    assert p["min_time_score"] == 0.35
    assert p["require_snd_clear"] is True


def test_hypothesis_search_is_bounded():
    c = propose_hypotheses(_bounded({}))
    assert 1 <= len(c) <= 5
    assert all(0.55 <= x["min_combined_score"] <= 0.95 for x in c)


def test_challenge_rejects_small_oos_sample():
    d = deterministic_challenge({}, {}, {"trades": 30, "expectancy_r": 0.2, "profit_factor": 1.3, "max_drawdown_pct": 5},
                                {"trades": 5, "expectancy_r": 0.5, "profit_factor": 2, "max_drawdown_pct": 2})
    assert not d["pass"]
    assert "insufficient_oos_sample" in d["reasons"]

def test_no_promotion_when_edge_is_not_robust():
    from src.autonomous_research import deterministic_challenge
    d = deterministic_challenge(
        {"expectancy_r": 0.10, "profit_factor": 1.10, "max_drawdown_pct": 8},
        {},
        {"trades": 30, "expectancy_r": 0.20, "profit_factor": 1.2, "max_drawdown_pct": 7},
        {"trades": 25, "expectancy_r": 0.08, "profit_factor": 1.02, "max_drawdown_pct": 9},
    )
    assert not d["pass"]
