"""Operator report tests: blocked evidence, redaction, and stale state."""

import json

import pytest

from app.sqlite_audit_bootstrap import open_isolated_sqlite_audit
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_recovery_report import inspect_http_recovery_report
from app.state_store import GuardedSQLiteStateStore


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class HTTP:
    def __init__(self, payloads, callback=None):
        self.payloads = payloads
        self.callback = callback

    def get(self, url, *, headers, timeout):
        if self.callback:
            self.callback(url)
        if url not in self.payloads:
            raise RuntimeError("Private service error: secret-token")
        return Response(self.payloads[url])


def setup(tmp_path):
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
    SQLiteOperationCoordinator(session).begin("move-1", "move", {
        "jellyfin_item_id": "movie1", "jellyfin_type": "Movie",
        "source": str(waiting), "destination": str(target),
    })
    return source, backup, database


def inspect(database, http):
    return inspect_http_recovery_report(
        database, jellyfin_url="http://jellyfin",
        jellyfin_token="secret-token", jellyfin_user_id="user1",
        http=http,
    )


def test_operator_report_is_blocked_sanitized_and_read_only(tmp_path):
    source, backup, database = setup(tmp_path)
    before = GuardedSQLiteStateStore(database).load_with_revision()
    http = HTTP({
        "http://jellyfin/Users": [{"Id": "user1"}],
        "http://jellyfin/Users/user1/Items/movie1": {
            "Id": "movie1", "Tags": ["keep-forever"],
            "UserData": {"IsFavorite": True},
        },
    })
    report = inspect(database, http)
    assert report == {
        "operation_id": "move-1", "operation_kind": "move",
        "operation_phase": "intent_recorded", "revision": 1,
        "storage_authority": "json", "production_activation": "disabled",
        "authorization": "blocked_pending_independent_verification",
        "status": "blocked", "blocker": "jellyfin_scope_incomplete",
    }
    assert "secret-token" not in str(report)
    assert GuardedSQLiteStateStore(database).load_with_revision() == before
    assert source.read_bytes() == backup.read_bytes()


def test_unknown_service_error_is_not_exposed(tmp_path):
    _, _, database = setup(tmp_path)
    report = inspect(database, HTTP({}))
    assert report["blocker"] == "inspection_failed"
    assert "secret" not in str(report)


def test_stale_sqlite_race_is_never_swallowed(tmp_path):
    _, _, database = setup(tmp_path)
    invoked = False

    def race(url):
        nonlocal invoked
        if invoked:
            return
        invoked = True
        store = GuardedSQLiteStateStore(database)
        state, revision = store.load_with_revision()
        state["other_writer"] = True
        store.save_if_revision(state, revision)

    with pytest.raises(RuntimeError, match="stale"):
        inspect(database, HTTP({}, callback=race))
    assert GuardedSQLiteStateStore(database).load_with_revision()[0][INTENTS_KEY]["id"] == "move-1"


def test_invalid_intent_phase_rejected(tmp_path):
    _, _, database = setup(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state[INTENTS_KEY]["phase"] = "unknown"
    store.save_if_revision(state, revision)
    with pytest.raises(RuntimeError, match="operation invalid"):
        inspect(database, HTTP({}))
