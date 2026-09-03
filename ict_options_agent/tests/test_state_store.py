"""
Unit tests for src/state_store.py.

Each test gets a fresh SQLite file via the fresh_db fixture so tests can't
leak state into each other or into the real data/agent_state.db.
"""
import pytest
from pathlib import Path
import src.state_store as state_store


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_state.db"
    monkeypatch.setattr(state_store, "DB_PATH", db_path)
    state_store.init_db()
    return db_path


# ---------------- signal hashing ----------------

def test_signal_hash_deterministic(fresh_db):
    h1 = state_store.make_signal_hash("SPY", "directional", "bull", "silver_bullet")
    h2 = state_store.make_signal_hash("SPY", "directional", "bull", "silver_bullet")
    assert h1 == h2


def test_signal_hash_differs_by_symbol(fresh_db):
    h1 = state_store.make_signal_hash("SPY", "directional", "bull", "silver_bullet")
    h2 = state_store.make_signal_hash("QQQ", "directional", "bull", "silver_bullet")
    assert h1 != h2


def test_signal_hash_differs_by_bias(fresh_db):
    h1 = state_store.make_signal_hash("SPY", "directional", "bull", "silver_bullet")
    h2 = state_store.make_signal_hash("SPY", "directional", "bear", "silver_bullet")
    assert h1 != h2


def test_signal_hash_differs_by_window(fresh_db):
    h1 = state_store.make_signal_hash("SPY", "directional", "bull", "silver_bullet")
    h2 = state_store.make_signal_hash("SPY", "directional", "bull", "ny_open")
    assert h1 != h2


def test_client_order_id_derived_from_hash_is_stable(fresh_db):
    h = state_store.make_signal_hash("SPY", "directional", "bull", "silver_bullet")
    assert state_store.make_client_order_id(h) == state_store.make_client_order_id(h)


# ---------------- order idempotency ----------------

def test_no_active_order_initially(fresh_db):
    h = state_store.make_signal_hash("SPY", "directional", "bull", "silver_bullet")
    assert state_store.has_active_order_for_signal(h) is False


def test_pending_order_counts_as_active(fresh_db):
    h = state_store.make_signal_hash("SPY", "directional", "bull", "silver_bullet")
    coid = state_store.make_client_order_id(h)
    state_store.record_pending_order(coid, "SPY", "directional", h, 2, 1.25, "[]")
    assert state_store.has_active_order_for_signal(h) is True


def test_submitted_order_counts_as_active(fresh_db):
    h = state_store.make_signal_hash("SPY", "directional", "bull", "silver_bullet")
    coid = state_store.make_client_order_id(h)
    state_store.record_pending_order(coid, "SPY", "directional", h, 2, 1.25, "[]")
    state_store.mark_order_submitted(coid, "broker-abc")
    assert state_store.has_active_order_for_signal(h) is True


def test_failed_order_does_not_block_retry(fresh_db):
    h = state_store.make_signal_hash("SPY", "directional", "bull", "silver_bullet")
    coid = state_store.make_client_order_id(h)
    state_store.record_pending_order(coid, "SPY", "directional", h, 2, 1.25, "[]")
    state_store.mark_order_failed(coid)
    assert state_store.has_active_order_for_signal(h) is False


def test_record_pending_order_is_idempotent_insert(fresh_db):
    """INSERT OR IGNORE — calling record_pending_order twice with the same
    client_order_id must not raise or create a duplicate row."""
    h = state_store.make_signal_hash("SPY", "directional", "bull", "silver_bullet")
    coid = state_store.make_client_order_id(h)
    state_store.record_pending_order(coid, "SPY", "directional", h, 2, 1.25, "[]")
    state_store.record_pending_order(coid, "SPY", "directional", h, 99, 9.99, "[]")  # different payload
    row = state_store.get_order_by_client_id(coid)
    assert row["qty"] == 2  # first insert wins, second was ignored


def test_get_order_by_client_id_returns_none_when_missing(fresh_db):
    assert state_store.get_order_by_client_id("does-not-exist") is None


def test_mark_order_submitted_updates_status_and_broker_id(fresh_db):
    h = state_store.make_signal_hash("SPY", "directional", "bull", "silver_bullet")
    coid = state_store.make_client_order_id(h)
    state_store.record_pending_order(coid, "SPY", "directional", h, 2, 1.25, "[]")
    state_store.mark_order_submitted(coid, "broker-xyz")
    row = state_store.get_order_by_client_id(coid)
    assert row["status"] == "submitted"
    assert row["broker_order_id"] == "broker-xyz"


# ---------------- daily stats / kill switch persistence ----------------

def test_daily_stats_created_on_first_call(fresh_db):
    stats = state_store.get_or_init_daily_stats(100_000.0)
    assert stats["starting_equity"] == 100_000.0
    assert stats["halted"] == 0


def test_daily_stats_starting_equity_locked_after_first_call(fresh_db):
    state_store.get_or_init_daily_stats(100_000.0)
    stats = state_store.get_or_init_daily_stats(50_000.0)  # should be ignored
    assert stats["starting_equity"] == 100_000.0


def test_set_halted_persists(fresh_db):
    state_store.get_or_init_daily_stats(100_000.0)
    state_store.set_halted("test breach")
    stats = state_store.get_or_init_daily_stats(90_000.0)
    assert stats["halted"] == 1
    assert stats["halted_reason"] == "test breach"


def test_increment_trade_count(fresh_db):
    state_store.get_or_init_daily_stats(100_000.0)
    state_store.increment_trade_count()
    state_store.increment_trade_count()
    stats = state_store.get_or_init_daily_stats(100_000.0)
    assert stats["trades_count"] == 2


def test_db_file_actually_created_on_disk(fresh_db):
    assert Path(fresh_db).exists()
