"""One captured source, detached consumers and explicit SQLite comparisons."""
import json
import pytest
from app.dashboard_tracking_snapshot import (read_json_dashboard_snapshot,
                                            read_experimental_sqlite_dashboard_snapshot)
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def state():
    value = {section: {} for section in SECTIONS}
    value["first_seen"]["Example"] = "2024-01-01T00:00:00"
    value["legacy"] = {"nested": ["caf\u00e9"]}
    return value


def test_json_snapshot_is_captured_once_and_detached(tmp_path):
    path = tmp_path / "state.json"
    original = state()
    path.write_text(json.dumps(original))
    snapshot = read_json_dashboard_snapshot(path)
    consumer = snapshot.state
    consumer["legacy"]["nested"].append("mutation")
    path.write_text("{}")
    assert snapshot.state == original
    assert snapshot.metadata["storage_authority"] == "json"
    assert snapshot.revision is None


@pytest.mark.parametrize("raw", ['[]', '{"first_seen":[]}', '{"x":1,"x":2}',
    '{"first_seen":{"Example":"bad timestamp"}}', '{"unknown":NaN}'])
def test_invalid_json_tracking_is_visible_error(tmp_path, raw):
    path = tmp_path / "state.json"
    path.write_text(raw)
    with pytest.raises(RuntimeError, match="tracking state is unreadable"):
        read_json_dashboard_snapshot(path)


def test_interrupted_missing_json_is_not_empty_installation(tmp_path):
    (tmp_path / ".auditor_state_interrupted.tmp").write_text("partial")
    with pytest.raises(RuntimeError, match="tracking state is unreadable"):
        read_json_dashboard_snapshot(tmp_path / "missing.json")


def test_legacy_missing_sections_are_not_rewritten(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"legacy":{"preserve":true}}')
    assert read_json_dashboard_snapshot(path).state == {"legacy": {"preserve": True}}
    assert read_json_dashboard_snapshot(tmp_path / "fresh.json").state == {}


def test_experimental_sqlite_revision_is_checked_without_json_fallback(tmp_path):
    database = tmp_path / "state.db"
    write_offline_snapshot(state(), database)
    snapshot = read_experimental_sqlite_dashboard_snapshot(database)
    assert snapshot.revision == 0 and snapshot.state == state()
    snapshot.verify_current()
    other = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    other.checkpoint()
    with pytest.raises(RuntimeError, match="session is stale"):
        snapshot.verify_current()
    with pytest.raises(RuntimeError):
        read_experimental_sqlite_dashboard_snapshot(tmp_path / "missing.db")


def test_live_dashboard_never_falls_back_to_json_when_sqlite_is_unapproved(tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
    monkeypatch.setenv("WEB_SESSION_SECRET", "disposable-dashboard-source-secret")
    import web
    source = tmp_path / "authoritative.json"
    source.write_text('{"legacy":{"authority":"json"}}')
    monkeypatch.setattr(web, "STATE_FILE", str(source))
    monkeypatch.setenv("AUDITOR_STATE_BACKEND", "sqlite")
    with pytest.raises(RuntimeError, match="SQLite production activation is disabled"):
        web.load_state()
