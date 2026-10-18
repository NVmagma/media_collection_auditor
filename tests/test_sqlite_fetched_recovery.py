"""Independent fetcher contract tests; no real services or production media."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.sqlite_audit_bootstrap import open_isolated_sqlite_audit
from app.sqlite_fetched_recovery import inspect_fetched_recovery
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.state_store import GuardedSQLiteStateStore

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
PROTECTION = {
    "available": True, "complete": True, "keep": False,
    "keep_forever": False, "keep_all_seasons": False, "favorite": False,
}


def _setup(tmp_path, kind="arr_sync"):
    source, backup, database = (
        tmp_path / "source.json", tmp_path / "backup.json", tmp_path / "audit.db"
    )
    source.write_text(json.dumps({"legacy": {"history": ["waiting", "keep"]}}))
    create_offline_migration_snapshot(source, backup, database)
    session = open_isolated_sqlite_audit(source, backup, database)
    details = {"jellyfin_item_id": "jf-17"}
    if kind == "arr_sync":
        details.update(service="radarr", title_id=17,
                       root="/media/Movies_keep", monitored=True)
    else:
        waiting, kept = tmp_path / "Waiting" / "Movie", tmp_path / "Keep" / "Movie"
        waiting.mkdir(parents=True)
        kept.parent.mkdir()
        details.update(source=str(waiting), destination=str(kept))
    SQLiteOperationCoordinator(session).begin("op-1", kind, details)
    return database


def _reply(service, title_id, data, observed_at=NOW):
    return {"service": service, "title_id": title_id,
            "observed_at": observed_at, "data": data}


def _jellyfin(title_id):
    return _reply("jellyfin", title_id, PROTECTION)


def _arr(service, title_id):
    return _reply(service, str(title_id), {
        "id": title_id, "path": "/media/Movies_keep/Movie", "monitored": True,
    })


def test_fetched_arr_recovery_remains_blocked_and_read_only(tmp_path):
    database = _setup(tmp_path)
    before = GuardedSQLiteStateStore(database).load_with_revision()
    report = inspect_fetched_recovery(
        database, jellyfin_fetch=_jellyfin, arr_fetch=_arr, now=NOW
    )
    assert report["observation"] == "matching_record_unverified"
    assert report["authorization"] == "blocked_pending_independent_verification"
    assert report["revision"] == 1
    assert GuardedSQLiteStateStore(database).load_with_revision() == before
    assert before[0][INTENTS_KEY]["phase"] == "intent_recorded"


def test_fetched_move_checks_disposable_filesystem(tmp_path):
    database = _setup(tmp_path, kind="move")
    report = inspect_fetched_recovery(database, jellyfin_fetch=_jellyfin, now=NOW)
    assert report["observation"] == "not_started"
    assert report["production_activation"] == "disabled"


@pytest.mark.parametrize("observed", [
    NOW - timedelta(minutes=1),
    NOW + timedelta(seconds=1),
    datetime(2026, 10, 18),
])
def test_stale_future_or_naive_observation_rejected(tmp_path, observed):
    database = _setup(tmp_path)
    with pytest.raises(RuntimeError, match="timestamp|stale|future"):
        inspect_fetched_recovery(
            database, jellyfin_fetch=lambda item: _reply(
                "jellyfin", item, PROTECTION, observed
            ), arr_fetch=_arr, now=NOW,
        )


def test_wrong_identity_and_missing_arr_fetcher_rejected(tmp_path):
    database = _setup(tmp_path)
    with pytest.raises(RuntimeError, match="identity"):
        inspect_fetched_recovery(
            database, jellyfin_fetch=lambda item: _reply(
                "jellyfin", "other-title", PROTECTION
            ), arr_fetch=_arr, now=NOW,
        )
    with pytest.raises(RuntimeError, match="fetcher unavailable"):
        inspect_fetched_recovery(database, jellyfin_fetch=_jellyfin, now=NOW)


def test_incomplete_jellyfin_protection_blocks(tmp_path):
    database = _setup(tmp_path)
    with pytest.raises(RuntimeError, match="incomplete"):
        inspect_fetched_recovery(
            database, jellyfin_fetch=lambda item: _reply(
                "jellyfin", item, {**PROTECTION, "complete": False}
            ), arr_fetch=_arr, now=NOW,
        )


def test_protected_jellyfin_title_cannot_be_cleared(tmp_path):
    database = _setup(tmp_path)
    report = inspect_fetched_recovery(
        database, jellyfin_fetch=lambda item: _reply(
            "jellyfin", item, {**PROTECTION, "keep_forever": True}
        ), arr_fetch=_arr, now=NOW,
    )
    assert report["jellyfin_protection"] == "protected_manual_review_required"
    assert report["authorization"] == "blocked_pending_independent_verification"
