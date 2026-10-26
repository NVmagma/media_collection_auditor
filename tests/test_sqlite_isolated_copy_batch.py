"""Action caps and fail-stop behavior use actual isolated copy completion."""
from copy import deepcopy

import pytest

from app.sqlite_isolated_copy_batch import run_isolated_copy_batch
from app.sqlite_collected_isolated_runner import run_collected_isolated_copy_completion
from app.state_store import GuardedSQLiteStateStore
from tests.test_sqlite_collected_isolated_runner import lab, item, NOW, FOLDER, LIMITS


def setup(tmp_path):
    root, database = lab(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    folders = [FOLDER, "Second Movie", "Third Movie"]
    jobs, records = [], []
    for index, folder in enumerate(folders):
        if index:
            (root / "transient" / folder).mkdir()
            (root / "transient" / folder / "payload").write_text("fixture")
            state["first_seen"][folder] = "2024-01-01T00:00:00"
        jobs.append({"operation_id": "batch-" + str(index), "media_key": folder,
                     "title_folder": folder, "jellyfin_type": "Movie"})
        record = deepcopy(item(identity=str(index)))
        record["Path"] = "/media/" + folder + "/movie.mkv"
        records.append(record)
    store.save_if_revision(state, revision)
    return root, database, jobs, records, revision + 1


def execute(root, database, jobs, revision, fetch, cap=2, **kwargs):
    return run_isolated_copy_batch(root=root, database=database, jobs=jobs,
        expected_revision=revision, max_actions_per_run=cap, thresholds=LIMITS,
        fetch=fetch, clock=lambda: NOW, **kwargs)


def transport(records, *, fail_scan=None):
    scans = []
    def fetch(path, params):
        if path == "/Users":
            scans.append(path)
            return [{"Id": "user"}]
        selected = [] if fail_scan and len(scans) >= fail_scan else [
            record for record in records if record["Type"] == params["IncludeItemTypes"]]
        return {"TotalRecordCount": len(selected), "Items": selected}
    return fetch, scans


@pytest.mark.parametrize("cap", [-1, True, "2", None])
def test_invalid_caps_stop_before_collection_or_state_change(tmp_path, cap):
    root, database, jobs, _, revision = setup(tmp_path)
    before = database.read_bytes()
    with pytest.raises(ValueError, match="integer cap"):
        execute(root, database, jobs, revision, lambda *args: pytest.fail("no fetch"), cap=cap)
    assert database.read_bytes() == before
    assert not (root / ".sqlite_copy_staging").exists()


@pytest.mark.parametrize("invalid", ["duplicate_key", "duplicate_operation", "unsafe_folder", "extra_field", "bad_arr", "physical_collision"])
def test_entire_selection_validated_even_beyond_cap(tmp_path, invalid):
    root, database, jobs, _, revision = setup(tmp_path)
    before = database.read_bytes()
    if invalid == "duplicate_key":
        jobs[2] = deepcopy(jobs[0])
    elif invalid == "duplicate_operation":
        jobs[2]["operation_id"] = jobs[0]["operation_id"]
    elif invalid == "unsafe_folder":
        jobs[2]["title_folder"] = "../outside"
    elif invalid == "extra_field":
        jobs[2]["fault_at"] = "after_completion_checkpoint"
    elif invalid == "physical_collision":
        jobs[2].update(title_folder=FOLDER, media_key="TV/" + FOLDER, jellyfin_type="Series")
    else:
        jobs[2]["arr_sync_request"] = {"service": "radarr", "title_id": True, "root": "/fixture", "monitored": False}
    with pytest.raises((ValueError, RuntimeError)):
        execute(root, database, jobs, revision, lambda *args: pytest.fail("no fetch"), cap=1)
    assert database.read_bytes() == before
    assert not (root / ".sqlite_copy_staging").exists()


def test_zero_cap_never_collects_or_moves(tmp_path):
    root, database, jobs, _, revision = setup(tmp_path)
    before = database.read_bytes()
    report = execute(root, database, jobs, revision, lambda *args: pytest.fail("no fetch"), cap=0)
    assert report["status"] == "cap_reached" and report["attempted_titles"] == 0
    assert report["unattempted_titles"] == 3 and database.read_bytes() == before
    assert not (root / ".sqlite_copy_staging").exists()


@pytest.mark.parametrize("blocker", ["stale", "pending", "conflicting_clock", "arr_queue", "reused_operation"])
def test_state_preflight_blocks_before_transport(tmp_path, blocker):
    root, database, jobs, _, revision = setup(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, current = store.load_with_revision()
    if blocker == "pending":
        state["sqlite_pending_operations"] = {}
    elif blocker == "conflicting_clock":
        state["queued"][jobs[2]["media_key"]] = "2024-01-01T00:00:00"
    elif blocker == "arr_queue":
        state["arr_sync_pending"][jobs[2]["media_key"]] = {"stage": "holding", "service": "radarr", "title_id": 99, "root": "/fixture", "monitored": False}
    elif blocker == "reused_operation":
        state["sqlite_retained_sources"] = {jobs[2]["operation_id"]: {"preserved": True}}
    store.save_if_revision(state, current)
    if blocker != "stale":
        revision += 1
    before = database.read_bytes()
    with pytest.raises(RuntimeError):
        execute(root, database, jobs, revision, lambda *args: pytest.fail("no fetch"))
    assert database.read_bytes() == before


def test_collection_failure_stops_batch_and_redacts_transport_details(tmp_path):
    root, database, jobs, _, revision = setup(tmp_path)
    calls = []
    def failed(path, params):
        calls.append(path)
        raise RuntimeError("private-key-and-host")
    report = execute(root, database, jobs, revision, failed)
    assert report["status"] == "blocked" and report["attempted_titles"] == 1
    assert report["confirmed_completed_titles"] == 0 and report["unattempted_titles"] == 2
    assert report["last_attempt_outcome_unverified"] and not report["retry_authorized"]
    assert calls == ["/Users"] and "private" not in str(report) and FOLDER not in str(report)
    assert not (root / ".sqlite_copy_staging").exists()


def test_outer_batch_lock_excludes_another_collected_runner(tmp_path):
    root, database, jobs, records, revision = setup(tmp_path)
    fetch, _ = transport(records)
    attempted = []
    def contended(path, params):
        if not attempted:
            attempted.append(True)
            with pytest.raises(RuntimeError, match="Another isolated SQLite runner"):
                run_collected_isolated_copy_completion(root=root, database=database, **jobs[1],
                    thresholds=LIMITS, fetch=lambda *args: pytest.fail("contender must not fetch"))
        return fetch(path, params)
    report = execute(root, database, jobs, revision, contended, cap=1)
    assert attempted == [True] and report["attempted_titles"] == 1
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert jobs[1]["media_key"] in state["first_seen"]


def test_actual_capability_completes_within_cap_or_stops_with_prepared_intent(tmp_path):
    root, database, jobs, records, revision = setup(tmp_path)
    fetch, scans = transport(records)
    report = execute(root, database, jobs, revision, fetch, cap=2)
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    if report["status"] == "blocked":
        assert report["attempted_titles"] == 1 and report["confirmed_completed_titles"] == 0
        assert state["sqlite_pending_operations"]["details"]["publication"]["phase"] == "prepared"
        assert (root / "transient" / jobs[0]["title_folder"] / "payload").read_text() == "fixture"
        assert len(scans) == 5
    else:
        assert report["status"] == "cap_reached" and report["confirmed_completed_titles"] == 2
        assert len(state["sqlite_retained_sources"]) == 2 and len(scans) == 18
    assert (root / "transient" / jobs[2]["title_folder"] / "payload").read_text() == "fixture"


@pytest.mark.parametrize("entry", ["run_collected_isolated_move", "run_collected_isolated_copy", "run_collected_isolated_copy_completion"])
def test_public_single_title_entry_cannot_accept_internal_lock_bypass(tmp_path, entry):
    import app.sqlite_collected_isolated_runner as collected
    root, database, jobs, _, _ = setup(tmp_path)
    before = database.read_bytes()
    with pytest.raises(TypeError, match="_held_runner_binding"):
        getattr(collected, entry)(root=root, database=database, **jobs[0], thresholds=LIMITS,
            fetch=lambda *args: pytest.fail("no fetch"), _held_runner_binding=lambda: None)
    assert database.read_bytes() == before
