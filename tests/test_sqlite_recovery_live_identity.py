"""Live identity inspection remains read-only and fail-closed."""

from datetime import datetime, timezone

import pytest

from app import sqlite_recovery_live_identity as live


class Session:
    def __init__(self, store):
        self.reads = 0

    def read_verified_snapshot(self):
        self.reads += 1
        return ({
            "sqlite_pending_operations": {
                "kind": "move", "phase": "intent_recorded",
                "details": {
                    "jellyfin_type": "Movie", "jellyfin_item_id": "jf1",
                    "arr_title_id": 8, "external_id": "tt1234567",
                },
            },
        }, 4)


class Adapter:
    def __init__(self, **kwargs):
        self.calls = []

    def jellyfin_fetch_identity(self, item_id):
        assert item_id == "jf1"
        return {"service": "jellyfin", "title_id": item_id,
                "observed_at": datetime.now(timezone.utc),
                "data": {"Id": item_id, "Type": "Movie",
                         "ProviderIds": {"Imdb": "tt1234567"}}}

    def arr_fetch(self, service, title_id):
        assert (service, title_id) == ("radarr", 8)
        return {"service": service, "title_id": str(title_id),
                "observed_at": datetime.now(timezone.utc),
                "data": {"id": title_id, "imdbId": "tt1234567"}}


def setup(monkeypatch):
    monkeypatch.setattr(live, "RevisionedAuditSession", Session)
    monkeypatch.setattr(live, "GuardedSQLiteStateStore", lambda _: None)
    monkeypatch.setattr(live, "inspect_pending_move_filesystem",
                        lambda _: {"revision": 4,
                                   "interpretation": "destination_only_unverified"})
    monkeypatch.setattr(live, "ReadOnlyRecoveryHTTP", Adapter)


def test_live_consistent_identity_remains_blocked(monkeypatch):
    setup(monkeypatch)
    result = live.inspect_live_move_identity("unused.db")
    assert result["identity_verification"] == "consistent_not_authoritative"
    assert result["filesystem_interpretation"] == "destination_only_unverified"
    assert result["authorization"] == "not_authorized"
    assert result["reconciliation"] == "disabled"
    assert "tt1234567" not in str(result)


def test_live_service_error_is_redacted_and_blocked(monkeypatch):
    setup(monkeypatch)
    class FailedAdapter(Adapter):
        def arr_fetch(self, service, title_id):
            raise RuntimeError("secret-token")
    monkeypatch.setattr(live, "ReadOnlyRecoveryHTTP", FailedAdapter)
    result = live.inspect_live_move_identity("unused.db")
    assert result["identity_reason"] == "service_inspection_failed"
    assert "secret-token" not in str(result)


def test_filesystem_revision_conflict_prevents_external_calls(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(live, "inspect_pending_move_filesystem",
                        lambda _: {"revision": 5, "interpretation": "source_only"})
    with pytest.raises(RuntimeError, match="stale"):
        live.inspect_live_move_identity("unused.db")


def test_second_snapshot_race_rejected(monkeypatch):
    setup(monkeypatch)
    class ChangedSession(Session):
        def read_verified_snapshot(self):
            state, revision = super().read_verified_snapshot()
            if self.reads > 1:
                raise RuntimeError("SQLite recovery session is stale")
            return state, revision
    monkeypatch.setattr(live, "RevisionedAuditSession", ChangedSession)
    with pytest.raises(RuntimeError, match="stale"):
        live.inspect_live_move_identity("unused.db")


def test_path_binding_not_evaluated_when_identity_mismatches(monkeypatch):
    setup(monkeypatch)
    class MismatchedAdapter(Adapter):
        def arr_fetch(self, service, title_id):
            record = super().arr_fetch(service, title_id)
            record["data"]["imdbId"] = "tt9999999"
            return record
    monkeypatch.setattr(live, "ReadOnlyRecoveryHTTP", MismatchedAdapter)
    def forbidden(*args, **kwargs):
        raise AssertionError("path comparison must not run on mismatched identity")
    monkeypatch.setattr(live, "inspect_move_path_binding", forbidden)
    result = live.inspect_live_move_identity("unused.db")
    assert result["identity_reason"] == "shared_identity_mismatch"
    assert result["path_binding"] == "unverified"
    assert result["path_binding_reason"] == "identity_not_consistent"
    assert result["authorization"] == "not_authorized"
