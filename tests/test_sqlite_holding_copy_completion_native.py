"""Real Holding moves, retained originals and atomic clock/queue outcomes."""
import sys
import pytest

from app.state_store import GuardedSQLiteStateStore
from app.sqlite_disposable_copy_inspection import inspect_disposable_copy
from tests.test_sqlite_holding_copy_completion import setup, run
from tests.test_sqlite_collected_isolated_runner import item, transport, NOW, FOLDER

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Actual atomic publication/quarantine required")


@pytest.mark.parametrize("destination,tags", [("removal", []), ("keep", ["keep-forever"])])
@pytest.mark.parametrize("fault", [None, "after_retirement_intent", "after_source_quarantine", "after_completion_checkpoint"])
def test_holding_completion_crashes_preserve_clock_and_original(tmp_path, destination, tags, fault):
    root, database = setup(tmp_path)
    fetch, _ = transport([[item(tags)]])
    request = {"service": "radarr", "title_id": 44, "root": "/fixture/" + destination, "monitored": False}
    if fault:
        with pytest.raises(RuntimeError, match="Injected completion crash"):
            run(root, database, fetch, arr_sync_request=request, completion_fault_at=fault)
    else:
        result = run(root, database, fetch, arr_sync_request=request)
        assert result["lifecycle_committed"] and not result["permanent_deletion_performed"]
    committed = fault in (None, "after_completion_checkpoint")
    retired = fault != "after_retirement_intent"
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert (FOLDER not in state["queued"]) is committed
    assert (FOLDER in state["in_removal" if destination == "removal" else "keep_seen"]) is committed
    assert (FOLDER in state["arr_sync_pending"]) is committed
    assert ("sqlite_pending_operations" not in state) is committed
    assert not state["first_seen"]
    original = root / ".sqlite_retained_sources" / "holding-copy" if retired else root / "holding" / FOLDER
    assert (original / "payload").read_text() == "fixture"
    assert (root / destination / FOLDER / "payload").read_text() == "fixture"
    if not committed:
        inspected = inspect_disposable_copy(root=root)
        assert inspected["proposed_source_stage"] == "holding"
        assert inspected["source_status"] == ("missing" if retired else "content_matches_unverified")
        with pytest.raises(RuntimeError, match="Unresolved"):
            run(root, database, lambda *args: pytest.fail("must not replay"))


@pytest.mark.parametrize("destination,tags", [("removal", []), ("keep", ["keep-forever"])])
@pytest.mark.parametrize("committed", [False, True])
def test_holding_final_checkpoint_is_all_or_nothing(tmp_path, monkeypatch, destination, tags, committed):
    root, database = setup(tmp_path)
    original = GuardedSQLiteStateStore.save_if_revision
    writes = 0
    def uncertain(self, state, revision):
        nonlocal writes
        writes += 1
        if writes == 6:
            if committed:
                original(self, state, revision)
            raise RuntimeError("injected Holding checkpoint uncertainty")
        return original(self, state, revision)
    monkeypatch.setattr(GuardedSQLiteStateStore, "save_if_revision", uncertain)
    fetch, _ = transport([[item(tags)]])
    with pytest.raises(RuntimeError, match="checkpoint uncertainty"):
        run(root, database, fetch)
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert (FOLDER in state["queued"]) is not committed
    assert (FOLDER in state["in_removal" if destination == "removal" else "keep_seen"]) is committed
    assert ("sqlite_pending_operations" not in state) is committed
    assert bool(state.get("sqlite_retained_sources")) is committed
    assert (root / ".sqlite_retained_sources" / "holding-copy" / "payload").read_text() == "fixture"


@pytest.mark.parametrize("tags,destination", [([], "removal"), (["keep-forever"], "keep")])
def test_whole_show_holding_transition_preserves_every_season(tmp_path, tags, destination):
    from tests.test_sqlite_collected_copy_series import series, KEY
    from app.sqlite_collected_isolated_runner import run_collected_isolated_copy_completion
    from tests.test_sqlite_collected_isolated_runner import LIMITS
    root, database = setup(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state["queued"][KEY] = state["queued"].pop(FOLDER)
    store.save_if_revision(state, revision)
    source = root / "holding" / FOLDER
    for season in ("Season 00", "Season 01", "Season 02"):
        (source / season).mkdir()
        (source / season / "episode.mkv").write_bytes(b"fixture episode")
    fetch, _ = transport([[series(tags)]])
    result = run_collected_isolated_copy_completion(root=root, database=database,
        operation_id="holding-series", media_key=KEY, title_folder=FOLDER,
        jellyfin_type="Series", thresholds=LIMITS, fetch=fetch, clock=lambda: NOW)
    assert result["original_bytes_retained"]
    for parent in (root / destination / FOLDER, root / ".sqlite_retained_sources" / "holding-series"):
        for season in ("Season 00", "Season 01", "Season 02"):
            assert (parent / season / "episode.mkv").read_bytes() == b"fixture episode"


def test_batch_can_mix_waiting_and_holding_without_revisiting_title(tmp_path):
    from tests.test_sqlite_isolated_copy_batch import setup as batch_setup, execute, transport as batch_transport
    root, database, jobs, records, revision = batch_setup(tmp_path)
    folder = jobs[1]["title_folder"]
    (root / "transient" / folder).rename(root / "holding" / folder)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state["queued"][folder] = state["first_seen"].pop(folder)
    store.save_if_revision(state, revision)
    fetch, scans = batch_transport(records)
    result = execute(root, database, jobs, revision + 1, fetch, cap=2)
    assert result["confirmed_completed_titles"] == 2 and len(scans) == 18
    state = store.load_with_revision()[0]
    assert jobs[0]["media_key"] in state["queued"]
    assert folder in state["in_removal"] and folder not in state["queued"]
    assert jobs[2]["media_key"] in state["first_seen"]
    assert len(state["sqlite_retained_sources"]) == 2


@pytest.mark.parametrize("phase", [6, 8])
def test_late_protection_change_keeps_holding_clock_and_pending_removal_copy(tmp_path, phase):
    root, database = setup(tmp_path)
    fetch, _ = transport([[item()]] * (phase - 1) + [[item(["keep-forever"])]])
    with pytest.raises(RuntimeError, match="changed"):
        run(root, database, fetch)
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert FOLDER in state["queued"] and not state["in_removal"] and not state["keep_seen"]
    assert "sqlite_pending_operations" in state and not state["arr_sync_pending"]
    original = root / "holding" / FOLDER if phase == 6 else root / ".sqlite_retained_sources" / "holding-copy"
    assert (original / "payload").read_text() == "fixture"
    assert (root / "removal" / FOLDER / "payload").read_text() == "fixture"
    inspected = inspect_disposable_copy(root=root)
    assert inspected["proposed_source_stage"] == "holding" and not inspected["recovery_authorized"]
