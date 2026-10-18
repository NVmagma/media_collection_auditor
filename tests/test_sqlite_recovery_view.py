"""Standalone experimental recovery view safety tests."""

import json

from flask import Flask

from app.sqlite_audit_bootstrap import open_isolated_sqlite_audit
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.sqlite_recovery_view import create_recovery_view_blueprint
from app.state_store import GuardedSQLiteStateStore


def setup(tmp_path, *, operation_id="op-1"):
    source, backup, database = (
        tmp_path / "state.json", tmp_path / "backup.json", tmp_path / "state.db"
    )
    source.write_text(json.dumps({"legacy": {"retained": True}}))
    create_offline_migration_snapshot(source, backup, database)
    session = open_isolated_sqlite_audit(source, backup, database)
    waiting = tmp_path / "Waiting" / "Movie"
    target = tmp_path / "Keep" / "Movie"
    waiting.mkdir(parents=True)
    target.parent.mkdir()
    SQLiteOperationCoordinator(session).begin(operation_id, "move", {
        "jellyfin_item_id": "movie1", "jellyfin_type": "Movie",
        "source": str(waiting), "destination": str(target),
    })
    return source, backup, database


def client(database, admin):
    app = Flask(__name__)
    app.register_blueprint(create_recovery_view_blueprint(
        database, is_admin=lambda: admin,
    ))
    return app.test_client()


def test_admin_view_is_read_only_and_discloses_no_media_paths(tmp_path):
    source, backup, database = setup(tmp_path)
    before = GuardedSQLiteStateStore(database).load_with_revision()
    response = client(database, True).get("/experimental/sqlite/recovery")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "op-1" in body
    assert "Recommended review" in body
    assert "Do not replay or clear" in body
    assert "blocked" in body
    assert "Production state remains JSON" in body
    assert "Waiting" not in body
    assert "Keep" not in body
    assert "movie1" not in body
    assert response.headers["Cache-Control"] == "no-store"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert GuardedSQLiteStateStore(database).load_with_revision() == before
    assert source.read_bytes() == backup.read_bytes()


def test_operation_id_is_html_escaped(tmp_path):
    _, _, database = setup(tmp_path, operation_id="<script>alert(1)</script>")
    body = client(database, True).get(
        "/experimental/sqlite/recovery"
    ).get_data(as_text=True)
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_non_admin_and_missing_database_fail_closed(tmp_path):
    _, _, database = setup(tmp_path)
    denied = client(database, False).get("/experimental/sqlite/recovery")
    assert denied.status_code == 403
    assert denied.headers["Cache-Control"] == "no-store"
    missing = tmp_path / "missing.db"
    response = client(missing, True).get("/experimental/sqlite/recovery")
    assert response.status_code == 503
    assert not missing.exists()


def test_corrupt_database_returns_generic_error(tmp_path):
    database = tmp_path / "corrupt.db"
    database.write_text("private-secret")
    response = client(database, True).get("/experimental/sqlite/recovery")
    assert response.status_code == 503
    assert "private-secret" not in response.get_data(as_text=True)


def test_no_write_method(tmp_path):
    _, _, database = setup(tmp_path)
    response = client(database, True).post("/experimental/sqlite/recovery")
    assert response.status_code == 405
