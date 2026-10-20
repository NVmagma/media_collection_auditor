"""Whole-show copy rehearsal preserves every season and honors refreshed flags."""
import pytest
from tests.test_sqlite_collected_isolated_runner import lab, transport, NOW, FOLDER, LIMITS
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_collected_isolated_runner import run_collected_isolated_copy
from app.sqlite_disposable_copy_inspection import inspect_disposable_copy
from app.state_store import GuardedSQLiteStateStore

KEY = "TV/" + FOLDER


def series(tags=None, identity="series-one", favorite=False):
    return {"Id": identity, "Type": "Series", "Path": "/media/TV/" + FOLDER,
            "Tags": tags or [], "UserData": {"Played": False, "PlayCount": 0,
                                               "IsFavorite": favorite}}


def setup(tmp_path):
    root, database = lab(tmp_path)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    session.state["first_seen"][KEY] = session.state["first_seen"].pop(FOLDER)
    session.checkpoint()
    source = root / "transient" / FOLDER
    for season in ("Season 00", "Season 01", "Season 02"):
        (source / season).mkdir()
        (source / season / "episode.mkv").write_bytes(b"disposable episode")
    (source / "Empty Season").mkdir()
    return root, database


def run(root, database, fetch):
    return run_collected_isolated_copy(root=root, database=database,
        operation_id="series-copy", media_key=KEY, title_folder=FOLDER,
        jellyfin_type="Series", thresholds=LIMITS, fetch=fetch, clock=lambda: NOW)


def test_whole_show_staging_preserves_seasons_and_tracking(tmp_path):
    root, database = setup(tmp_path)
    fetch, calls = transport([[series()]])
    result = run(root, database, fetch)
    assert calls.count("/Users") == 2
    assert result["source_retained"] and not result["lifecycle_committed"]
    for parent in (root / "transient" / FOLDER, root / ".sqlite_copy_staging" / "series-copy"):
        for season in ("Season 00", "Season 01", "Season 02"):
            assert (parent / season / "episode.mkv").read_bytes() == b"disposable episode"
        assert (parent / "Empty Season").is_dir()
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert KEY in state["first_seen"] and FOLDER not in state["first_seen"]
    assert not state["queued"] and not state["arr_sync_pending"]
    assert inspect_disposable_copy(root=root)["source_status"] == "content_matches_unverified"


@pytest.mark.parametrize("refresh", [series(["keep-forever"]), series(["keep-all-seasons"]),
    series(["keep"]), series(favorite=True), series(identity="another-series")])
def test_show_protection_or_identity_changes_prevent_staging(tmp_path, refresh):
    root, database = setup(tmp_path)
    before = database.read_bytes()
    fetch, _ = transport([[series()], [refresh]])
    with pytest.raises(RuntimeError, match="replan required"):
        run(root, database, fetch)
    assert database.read_bytes() == before
    assert not (root / ".sqlite_copy_staging").exists()
    assert (root / "transient" / FOLDER / "Season 02" / "episode.mkv").exists()


def test_ambiguous_series_match_blocks_before_intent(tmp_path):
    root, database = setup(tmp_path)
    before = database.read_bytes()
    fetch, _ = transport([[series(), series(identity="duplicate")]])
    with pytest.raises(RuntimeError, match="unambiguous"):
        run(root, database, fetch)
    assert database.read_bytes() == before
    assert not (root / ".sqlite_copy_staging").exists()
