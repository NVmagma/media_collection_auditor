"""The future SQLite audit boundary must not expose unguarded writes."""

import pytest

from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore, RevisionedStateStore


def _empty():
    return {section: {} for section in SECTIONS}


def test_guarded_adapter_matches_protocol_and_rejects_stale_state(tmp_path):
    path = tmp_path / "tracking.db"
    write_offline_snapshot(_empty(), path)
    first = GuardedSQLiteStateStore(path)
    second = GuardedSQLiteStateStore(path)
    first_state, revision = first.load_with_revision()
    stale_state, stale_revision = second.load_with_revision()
    first_state["first_seen"]["Movie"] = "2024-01-01T00:00:00"
    first.save_if_revision(first_state, revision)
    stale_state["keep_seen"]["Show"] = "2024-01-01T00:00:00"
    with pytest.raises(RuntimeError, match="Stale SQLite state revision"):
        second.save_if_revision(stale_state, stale_revision)
    assert second.load_with_revision() == (first_state, 1)


def test_guarded_adapter_has_no_unguarded_save_or_load(tmp_path):
    store = GuardedSQLiteStateStore(tmp_path / "missing.db")
    assert not hasattr(store, "save")
    assert not hasattr(store, "load")
    with pytest.raises(RuntimeError, match="unavailable"):
        store.load_with_revision()
