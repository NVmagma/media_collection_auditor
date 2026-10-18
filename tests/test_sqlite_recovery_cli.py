"""Offline recovery CLI tests using disposable SQLite state."""

import json

from app.sqlite_recovery_cli import run
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore
from tests.test_sqlite_recovery_report import setup


def test_cli_reports_blocked_intent_without_mutation(tmp_path, capsys):
    source, backup, database = setup(tmp_path)
    before = GuardedSQLiteStateStore(database).load_with_revision()
    assert run(["--database", str(database)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert report["operation_kind"] == "move"
    assert report["authorization"] == "blocked_pending_independent_verification"
    assert "source" not in report
    assert "destination" not in report
    assert GuardedSQLiteStateStore(database).load_with_revision() == before
    assert source.read_bytes() == backup.read_bytes()


def test_cli_missing_database_does_not_create_file(tmp_path, capsys):
    database = tmp_path / "missing.db"
    assert run(["--database", str(database)]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "error", "reason": "database_unavailable",
    }
    assert not database.exists()


def test_cli_invalid_pending_operation_is_redacted(tmp_path, capsys):
    _, _, database = setup(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state[INTENTS_KEY]["phase"] = "invalid-secret-path"
    store.save_if_revision(state, revision)
    assert run(["--database", str(database)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report == {"status": "error", "reason": "invalid_pending_operation"}
    assert "secret" not in str(report)


def test_cli_no_pending_operation(tmp_path, capsys):
    _, _, database = setup(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    del state[INTENTS_KEY]
    store.save_if_revision(state, revision)
    assert run(["--database", str(database)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "no_pending_operation"


def test_cli_corrupt_database_is_redacted(tmp_path, capsys):
    database = tmp_path / "broken.db"
    database.write_text("not a database with a secret")
    assert run(["--database", str(database)]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "error", "reason": "inspection_failed",
    }
