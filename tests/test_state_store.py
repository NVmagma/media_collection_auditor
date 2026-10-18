"""Storage boundary tests: existing JSON behavior remains authoritative."""

import pytest

from app.state_store import JsonStateStore


def test_json_adapter_delegates_to_existing_safety_checked_functions(tmp_path, monkeypatch):
    from app import collection_auditor

    path = tmp_path / "state.json"
    monkeypatch.setattr(collection_auditor, "STATE_FILE", str(path))
    seen = []
    state = {"first_seen": {"Movie": "2024-01-01T00:00:00"}}
    monkeypatch.setattr(collection_auditor, "load_state", lambda: state)
    monkeypatch.setattr(collection_auditor, "save_state", lambda value: seen.append(value))
    store = JsonStateStore(path)
    assert store.load() is state
    store.save(state)
    assert seen == [state]


def test_json_adapter_rejects_mismatched_state_path(tmp_path, monkeypatch):
    from app import collection_auditor

    monkeypatch.setattr(collection_auditor, "STATE_FILE", str(tmp_path / "actual.json"))
    store = JsonStateStore(tmp_path / "different.json")
    with pytest.raises(RuntimeError, match="differs"):
        store.load()
    with pytest.raises(RuntimeError, match="differs"):
        store.save({})
    assert list(tmp_path.iterdir()) == []
