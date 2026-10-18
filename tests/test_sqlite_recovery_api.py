"""Isolated Flask recovery status tests; production app is never imported."""

import json

from flask import Flask

from app.sqlite_audit_bootstrap import open_isolated_sqlite_audit
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_recovery_api import create_recovery_status_blueprint
from app.state_store import GuardedSQLiteStateStore


def setup(tmp_path):
    source, backup, database = (
        tmp_path / "source.json", tmp_path / "backup.json", tmp_path / "audit.db"
    )
    source.write_text(json.dumps({"legacy": {"retained": True}}))
    create_offline_migration_snapshot(source, backup, database)
    session = open_isolated_sqlite_audit(source, backup, database)
    src = tmp_path / "Waiting" / "Movie"
    dst = tmp_path / "Keep" / "Movie"
    src.mkdir(parents=True)
    dst.parent.mkdir()
    SQLiteOperationCoordinator(session).begin("op-1", "move", {
        "jellyfin_item_id": "movie1", "jellyfin_type": "Movie",
        "source": str(src), "destination": str(dst),
    })
    return source, backup, database


def client(database, *, authorized):
    app = Flask(__name__)
    app.register_blueprint(
        create_recovery_status_blueprint(database, is_admin=lambda: authorized)
    )
    return app.test_client()


def test_admin_reads_blocked_status_without_mutation(tmp_path):
    source, backup, database = setup(tmp_path)
    before = GuardedSQLiteStateStore(database).load_with_revision()
    response = client(database, authorized=True).get(
        "/api/experimental/sqlite/recovery-status"
    )
    assert response.status_code == 200
    report = response.get_json()
    assert report["ok"] is True
    assert report["status"] == "blocked"
    assert report["authorization"] == "blocked_pending_independent_verification"
    assert report["operation_phase"] == "intent_recorded"
    assert "Waiting" not in str(report)
    assert "Keep" not in str(report)
    assert response.headers["Cache-Control"] == "no-store"
    assert GuardedSQLiteStateStore(database).load_with_revision() == before
    assert source.read_bytes() == backup.read_bytes()


def test_non_admin_is_forbidden_even_with_query_override(tmp_path):
    _, _, database = setup(tmp_path)
    response = client(database, authorized=False).get(
        "/api/experimental/sqlite/recovery-status?admin=true"
    )
    assert response.status_code == 403
    assert response.get_json() == {"ok": False, "reason": "forbidden"}


def test_missing_database_does_not_get_created(tmp_path):
    database = tmp_path / "absent.db"
    response = client(database, authorized=True).get(
        "/api/experimental/sqlite/recovery-status"
    )
    assert response.status_code == 503
    assert response.get_json() == {
        "ok": False, "reason": "database_unavailable",
    }
    assert not database.exists()


def test_invalid_database_returns_redacted_failure(tmp_path):
    database = tmp_path / "corrupt.db"
    database.write_text("private token in corrupt database")
    response = client(database, authorized=True).get(
        "/api/experimental/sqlite/recovery-status"
    )
    assert response.status_code == 503
    assert response.get_json() == {"ok": False, "reason": "inspection_failed"}
    assert "private token" not in response.get_data(as_text=True)


def test_pending_intent_absent_is_safe(tmp_path):
    _, _, database = setup(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    del state[INTENTS_KEY]
    store.save_if_revision(state, revision)
    response = client(database, authorized=True).get(
        "/api/experimental/sqlite/recovery-status"
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "no_pending_operation"


def test_no_mutating_methods_exposed(tmp_path):
    _, _, database = setup(tmp_path)
    response = client(database, authorized=True).post(
        "/api/experimental/sqlite/recovery-status"
    )
    assert response.status_code == 405
