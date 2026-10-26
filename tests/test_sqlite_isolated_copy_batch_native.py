"""Require real atomic publication/quarantine capability; no syscall mocks."""
import sys

import pytest

from app.state_store import GuardedSQLiteStateStore
from tests.test_sqlite_isolated_copy_batch import setup, execute, transport

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Actual Linux publication/quarantine required")


@pytest.mark.parametrize("cap", [1, 2, 3])
def test_successful_titles_obey_cap_and_preserve_every_original(tmp_path, cap):
    root, database, jobs, records, revision = setup(tmp_path)
    records[1]["Tags"] = ["keep"]
    jobs[1]["arr_sync_request"] = {"service": "radarr", "title_id": 42, "root": "/fixture/keep", "monitored": False}
    fetch, scans = transport(records)
    report = execute(root, database, jobs, revision, fetch, cap=cap)
    assert report["status"] == ("cap_reached" if cap < 3 else "completed")
    assert report["attempted_titles"] == report["confirmed_completed_titles"] == cap
    assert report["unattempted_titles"] == 3 - cap and len(scans) == cap * 9
    assert not report["stopped_on_failure"] and not report["last_attempt_outcome_unverified"]
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert "sqlite_pending_operations" not in state
    assert len(state["sqlite_retained_sources"]) == cap
    for index, job in enumerate(jobs):
        folder = job["title_folder"]
        if index < cap:
            original = root / ".sqlite_retained_sources" / job["operation_id"]
            assert (original / "payload").read_text() == "fixture"
            assert not (root / "transient" / folder).exists()
            assert (root / ("keep" if index == 1 else "holding") / folder / "payload").read_text() == "fixture"
        else:
            assert (root / "transient" / folder / "payload").read_text() == "fixture"
            assert folder in state["first_seen"]
    assert bool(state["arr_sync_pending"]) is (cap >= 2)


def test_second_title_failure_keeps_first_commit_and_never_attempts_third(tmp_path):
    root, database, jobs, records, revision = setup(tmp_path)
    fetch, scans = transport(records, fail_scan=10)
    report = execute(root, database, jobs, revision, fetch, cap=3)
    assert report["status"] == "blocked" and report["attempted_titles"] == 2
    assert report["confirmed_completed_titles"] == 1 and report["unattempted_titles"] == 1
    assert len(scans) == 10
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert jobs[0]["media_key"] in state["queued"] and len(state["sqlite_retained_sources"]) == 1
    for job in jobs[1:]:
        assert job["media_key"] in state["first_seen"]
        assert (root / "transient" / job["title_folder"] / "payload").read_text() == "fixture"
    assert "sqlite_pending_operations" not in state


@pytest.mark.parametrize("committed", [False, True])
def test_uncertain_checkpoint_stops_without_claiming_or_replaying_title(tmp_path, monkeypatch, committed):
    root, database, jobs, records, revision = setup(tmp_path)
    original = GuardedSQLiteStateStore.save_if_revision
    writes = 0
    def uncertain(self, state, expected):
        nonlocal writes
        writes += 1
        if writes == 6:
            if committed:
                original(self, state, expected)
            raise RuntimeError("private uncertain checkpoint")
        return original(self, state, expected)
    monkeypatch.setattr(GuardedSQLiteStateStore, "save_if_revision", uncertain)
    fetch, scans = transport(records)
    report = execute(root, database, jobs, revision, fetch, cap=3)
    assert report["status"] == "blocked" and report["last_attempt_outcome_unverified"]
    assert report["attempted_titles"] == 1 and report["confirmed_completed_titles"] == 0
    assert report["unattempted_titles"] == 2 and len(scans) == 9 and writes == 6
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert ("sqlite_pending_operations" not in state) is committed
    assert (jobs[0]["media_key"] in state["queued"]) is committed
    assert (root / ".sqlite_retained_sources" / jobs[0]["operation_id"] / "payload").read_text() == "fixture"
    for job in jobs[1:]:
        assert (root / "transient" / job["title_folder"] / "payload").read_text() == "fixture"


def test_unexpected_writer_between_titles_stops_before_next_collection(tmp_path, monkeypatch):
    import app.sqlite_isolated_copy_batch as batch
    root, database, jobs, records, revision = setup(tmp_path)
    original = batch._run_collected_isolated_operation
    def external_write(**kwargs):
        result = original(**kwargs)
        store = GuardedSQLiteStateStore(database)
        state, current = store.load_with_revision()
        state["external_writer"] = True
        store.save_if_revision(state, current)
        return result
    monkeypatch.setattr(batch, "_run_collected_isolated_operation", external_write)
    fetch, scans = transport(records)
    report = execute(root, database, jobs, revision, fetch, cap=3)
    assert report["status"] == "blocked" and report["confirmed_completed_titles"] == 1
    assert report["attempted_titles"] == 2 and len(scans) == 9
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert state["external_writer"] is True
    assert len(state["sqlite_retained_sources"]) == 1
    assert jobs[1]["media_key"] in state["first_seen"]


def test_transport_cannot_mutate_captured_remaining_jobs(tmp_path):
    root, database, jobs, records, revision = setup(tmp_path)
    second = jobs[1]["media_key"]
    jobs[1]["arr_sync_request"] = {"service": "radarr", "title_id": 42, "root": "/fixture/hold", "monitored": False}
    fetch, scans = transport(records)
    def mutate(path, params):
        jobs[1]["media_key"] = "../unsafe"
        jobs[1]["operation_id"] = jobs[0]["operation_id"]
        jobs[1]["arr_sync_request"]["title_id"] = True
        return fetch(path, params)
    report = execute(root, database, jobs, revision, mutate, cap=2)
    assert report["confirmed_completed_titles"] == 2 and len(scans) == 18
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert state["arr_sync_pending"][second]["title_id"] == 42
    assert len(state["sqlite_retained_sources"]) == 2


def test_mixed_movie_and_whole_show_batch_preserves_seasons_and_typed_queue(tmp_path):
    root, database, jobs, records, revision = setup(tmp_path)
    folder = jobs[1]["title_folder"]
    key = "TV/" + folder
    jobs[1].update(media_key=key, jellyfin_type="Series",
        arr_sync_request={"service": "sonarr", "title_id": 77, "root": "/fixture/tv_hold", "monitored": True})
    records[1].update(Type="Series", Path="/media/TV/" + folder)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state["first_seen"][key] = state["first_seen"].pop(folder)
    store.save_if_revision(state, revision)
    source = root / "transient" / folder
    for season in ("Season 00", "Season 01", "Season 02"):
        (source / season).mkdir()
        (source / season / "episode.mkv").write_bytes(b"synthetic episode")
    (source / "Empty Season").mkdir()
    fetch, scans = transport(records)
    report = execute(root, database, jobs, revision + 1, fetch, cap=2)
    assert report["confirmed_completed_titles"] == 2 and len(scans) == 18
    for parent in (root / "holding" / folder, root / ".sqlite_retained_sources" / jobs[1]["operation_id"]):
        for season in ("Season 00", "Season 01", "Season 02"):
            assert (parent / season / "episode.mkv").read_bytes() == b"synthetic episode"
        assert (parent / "Empty Season").is_dir()
    state = store.load_with_revision()[0]
    assert state["arr_sync_pending"][key]["service"] == "sonarr"
    assert key in state["queued"] and jobs[2]["media_key"] in state["first_seen"]
