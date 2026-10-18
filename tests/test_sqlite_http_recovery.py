"""Persisted recovery through mocked HTTP, including races and failure gates."""

import json

import pytest

from app.sqlite_audit_bootstrap import open_isolated_sqlite_audit
from app.sqlite_http_recovery import inspect_http_recovery
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.state_store import GuardedSQLiteStateStore


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class HTTP:
    def __init__(self, mapping, callback=None):
        self.mapping = mapping
        self.callback = callback
        self.calls = []

    def get(self, url, *, headers, timeout):
        self.calls.append(url)
        if self.callback:
            self.callback(url)
        if url not in self.mapping:
            raise RuntimeError("Unexpected HTTP URL")
        return Response(self.mapping[url])


def fixture(tmp_path, *, media_type="Movie", kind="arr_sync"):
    source, backup, database = (
        tmp_path / "state.json", tmp_path / "backup.json", tmp_path / "state.db"
    )
    original = json.dumps({"legacy": {"history": ["waiting", "keep"]}})
    source.write_text(original)
    create_offline_migration_snapshot(source, backup, database)
    session = open_isolated_sqlite_audit(source, backup, database)
    details = {"jellyfin_item_id": "title1", "jellyfin_type": media_type}
    if kind == "arr_sync":
        details.update(service="sonarr" if media_type == "Series" else "radarr",
                       title_id=17, root="/media/Keep", monitored=True)
    else:
        src, dst = tmp_path / "Waiting" / "Title", tmp_path / "Keep" / "Title"
        src.mkdir(parents=True)
        dst.parent.mkdir()
        details.update(source=str(src), destination=str(dst))
    SQLiteOperationCoordinator(session).begin("op-1", kind, details)
    return source, backup, database, original


def mapping(*, media_type="Movie", protected=False):
    base = "http://jellyfin"
    title = {
        "Id": "title1", "Tags": [],
        "UserData": {"IsFavorite": protected},
    }
    result = {
        base + "/Users": [{"Id": "user1"}],
        base + "/Users/user1/Items/title1": title,
        "http://radarr/api/v3/movie/17": {
            "id": 17, "path": "/media/Keep/Title", "monitored": True,
        },
        "http://sonarr/api/v3/series/17": {
            "id": 17, "path": "/media/Keep/Title", "monitored": True,
        },
    }
    if media_type == "Series":
        result[base + "/Shows/title1/Seasons?UserId=user1&StartIndex=0&Limit=10000"] = {
            "Items": [{"Id": "season1", "SeriesId": "title1"}],
            "TotalRecordCount": 1,
        }
        result[base + "/Users/user1/Items/season1"] = {
            "Id": "season1", "Tags": ["keep-forever"] if protected else [],
            "UserData": {"IsFavorite": False},
        }
    return result


def inspect(database, http):
    return inspect_http_recovery(
        database, jellyfin_url="http://jellyfin", jellyfin_token="token",
        jellyfin_user_id="user1", radarr_url="http://radarr",
        radarr_key="key", sonarr_url="http://sonarr",
        sonarr_key="key", http=http,
    )


@pytest.mark.parametrize("media_type", ["Movie", "Series"])
def test_real_adapter_flow_fails_closed_without_state_mutation(tmp_path, media_type):
    source, backup, database, original = fixture(tmp_path, media_type=media_type)
    before = GuardedSQLiteStateStore(database).load_with_revision()
    http = HTTP(mapping(media_type=media_type))
    with pytest.raises(RuntimeError, match="protection information incomplete"):
        inspect(database, http)
    assert GuardedSQLiteStateStore(database).load_with_revision() == before
    assert source.read_text() == backup.read_text() == original
    assert before[0][INTENTS_KEY]["phase"] == "intent_recorded"
    assert any("/Users" in url for url in http.calls)
    if media_type == "Series":
        assert sum("/Seasons?" in url for url in http.calls) == 2


def test_protected_season_never_authorizes_recovery(tmp_path):
    _, _, database, _ = fixture(tmp_path, media_type="Series")
    with pytest.raises(RuntimeError, match="incomplete"):
        inspect(database, HTTP(mapping(media_type="Series", protected=True)))
    assert GuardedSQLiteStateStore(database).load_with_revision()[0][INTENTS_KEY]["id"] == "op-1"


def test_service_failure_does_not_write_state(tmp_path):
    _, _, database, _ = fixture(tmp_path)
    before = GuardedSQLiteStateStore(database).load_with_revision()
    with pytest.raises(RuntimeError):
        inspect(database, HTTP({}))
    assert GuardedSQLiteStateStore(database).load_with_revision() == before


def test_concurrent_state_change_rejected_even_when_http_fails(tmp_path):
    _, _, database, _ = fixture(tmp_path)
    def concurrent_write(url):
        if url.endswith("/Users"):
            store = GuardedSQLiteStateStore(database)
            state, revision = store.load_with_revision()
            state["race_marker"] = "other writer"
            store.save_if_revision(state, revision)
    with pytest.raises(RuntimeError, match="stale"):
        inspect(database, HTTP({}, callback=concurrent_write))


def test_missing_media_type_blocks_before_service_reads(tmp_path):
    _, _, database, _ = fixture(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    del state[INTENTS_KEY]["details"]["jellyfin_type"]
    store.save_if_revision(state, revision)
    http = HTTP(mapping())
    with pytest.raises(RuntimeError, match="media type"):
        inspect(database, http)
    assert http.calls == []
