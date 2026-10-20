from datetime import datetime

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_jellyfin_preview_bridge import preview_with_collected_jellyfin
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

NOW = datetime(2026, 10, 20, 12)
KEY = "Movies/Movie"
THRESHOLDS = {"Waiting": 7, "Holding": 7, "Removal": 7, "Keep": 0}


def lab(tmp_path):
    state = {section: {} for section in SECTIONS}
    state["first_seen"][KEY] = "2026-10-01T12:00:00"
    db = tmp_path / "state.db"
    write_offline_snapshot(state, db)
    return db


def fetch(path, params):
    if path == "/Users":
        return [{"Id": "user-1"}]
    return {"TotalRecordCount": 1, "Items": [{
        "Id": "movie-id", "Path": "/media/Movies/Movie/file.mkv",
        "Tags": ["keep-forever"],
        "UserData": {"Played": False, "PlayCount": 0, "IsFavorite": False},
    }]}


def run(db, fetcher=fetch, requests=None):
    if requests is None:
        requests = {KEY: {"jellyfin_type": "Movie", "folder": "Movie"}}
    return preview_with_collected_jellyfin(
        database=db, now=NOW, thresholds=THRESHOLDS,
        requests=requests, fetch=fetcher)


def test_protected_title_previews_keep_but_never_authorizes(tmp_path):
    db = lab(tmp_path)
    before = RevisionedAuditSession(GuardedSQLiteStateStore(db))
    result = run(db)
    row = result["preview"]["decisions"][0]
    assert row["candidate_action"] == "keep"
    assert row["authorization"] == "not_authorized"
    assert result["authorization"] == "not_authorized"
    assert result["freshness_independently_verified"] is False
    after = RevisionedAuditSession(GuardedSQLiteStateStore(db))
    assert after.revision == before.revision
    assert after.state == before.state


def test_partial_jellyfin_failure_blocks_preview(tmp_path):
    db = lab(tmp_path)
    def broken(path, params):
        if path == "/Users":
            return [{"Id": "user-1"}]
        raise TimeoutError("Jellyfin unavailable")
    result = run(db, broken)
    assert result["status"] == "blocked"
    assert result["preview"]["decisions"][0]["action"] == "none"
    assert "jellyfin_unavailable" in result["preview"]["decisions"][0]["blockers"]


def test_unrequested_tracked_title_is_not_assumed_unprotected(tmp_path):
    db = lab(tmp_path)
    result = run(db, requests={})
    assert result["preview"]["blocked_titles"] == 1
    assert result["preview"]["decisions"][0]["action"] == "none"
