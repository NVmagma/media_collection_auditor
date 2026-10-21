"""Non-deleting Holding transitions preserve original bytes and clock binding."""
import errno
import sys

import pytest

from app.sqlite_collected_isolated_runner import run_collected_isolated_copy_completion, run_collected_isolated_copy
from app.sqlite_disposable_copy_inspection import inspect_disposable_copy
from app.state_store import GuardedSQLiteStateStore
from tests.test_sqlite_collected_isolated_runner import lab, item, transport, NOW, FOLDER, LIMITS


def setup(tmp_path, source="holding"):
    root, database = lab(tmp_path)
    (root / "transient" / FOLDER).rename(root / source / FOLDER)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    section = {"holding": "queued", "removal": "in_removal", "keep": "keep_seen"}[source]
    state[section][FOLDER] = state["first_seen"].pop(FOLDER)
    store.save_if_revision(state, revision)
    return root, database


def run(root, database, fetch, **kwargs):
    return run_collected_isolated_copy_completion(root=root, database=database,
        operation_id="holding-copy", media_key=FOLDER, title_folder=FOLDER,
        jellyfin_type="Movie", thresholds=LIMITS, fetch=fetch, clock=lambda: NOW, **kwargs)


@pytest.mark.parametrize("tags,favorite,trigger,destination", [
    ([], False, True, "removal"), (["keep-forever"], False, True, "keep"),
    (["keep"], False, True, "keep"), ([], True, True, "keep"), ([], True, False, "removal")])
def test_actual_holding_capability_retains_source_or_commits_non_deleting_transition(tmp_path, tags, favorite, trigger, destination):
    root, database = setup(tmp_path)
    fetch, _ = transport([[item(tags, favorite=favorite)]])
    try:
        report = run(root, database, fetch, favorites_trigger_keep=trigger)
    except RuntimeError as exc:
        if sys.platform != "linux":
            assert str(exc) == "Atomic no-replace rename requires Linux"
        else:
            assert str(exc) == "Atomic no-replace rename unsupported"
            assert isinstance(exc.__cause__, OSError)
            assert exc.__cause__.errno in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP)
        state = GuardedSQLiteStateStore(database).load_with_revision()[0]
        assert FOLDER in state["queued"] and not state["in_removal"] and not state["keep_seen"]
        assert state["sqlite_pending_operations"]["details"]["plan_binding"]["source_stage"] == "holding"
        assert (root / "holding" / FOLDER / "payload").read_text() == "fixture"
        inspected = inspect_disposable_copy(root=root)
        assert inspected["proposed_source_stage"] == "holding"
        assert inspected["proposed_destination_stage"] == destination
        assert not inspected["recovery_authorized"]
    else:
        assert report["lifecycle_committed"] and not report["permanent_deletion_performed"]
        state = GuardedSQLiteStateStore(database).load_with_revision()[0]
        assert FOLDER not in state["queued"]
        assert state["in_removal" if destination == "removal" else "keep_seen"][FOLDER] == NOW.isoformat()
        assert (root / destination / FOLDER / "payload").read_text() == "fixture"
        assert (root / ".sqlite_retained_sources" / "holding-copy" / "payload").read_text() == "fixture"
        assert "sqlite_pending_operations" not in state


@pytest.mark.parametrize("refresh", [item(["keep-forever"]), item(favorite=True), item(identity="replacement")])
def test_changed_holding_protections_never_publish_old_removal_candidate(tmp_path, refresh):
    root, database = setup(tmp_path)
    fetch, _ = transport([[item()]] * 3 + [[refresh]])
    with pytest.raises(RuntimeError, match="changed"):
        run(root, database, fetch)
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert FOLDER in state["queued"] and not state["in_removal"]
    assert "publication" not in state["sqlite_pending_operations"]["details"]
    assert (root / "holding" / FOLDER / "payload").read_text() == "fixture"
    assert not (root / "removal" / FOLDER).exists()


@pytest.mark.parametrize("source", ["keep", "removal"])
def test_unsupported_sources_never_delete_or_create_copy_intent(tmp_path, source):
    root, database = setup(tmp_path, source)
    before = database.read_bytes()
    fetch, _ = transport([[item(["keep-forever"])]])
    with pytest.raises(RuntimeError, match="No collected lifecycle move candidate"):
        run(root, database, fetch)
    assert database.read_bytes() == before
    assert (root / source / FOLDER / "payload").read_text() == "fixture"
    assert not (root / ".sqlite_copy_staging").exists()


def test_existing_stage_only_entry_still_requires_waiting(tmp_path):
    root, database = setup(tmp_path)
    before = database.read_bytes()
    fetch, _ = transport([[item()]])
    with pytest.raises(RuntimeError, match="requires a Waiting"):
        run_collected_isolated_copy(root=root, database=database,
            operation_id="stage-only", media_key=FOLDER, title_folder=FOLDER,
            jellyfin_type="Movie", thresholds=LIMITS, fetch=fetch, clock=lambda: NOW)
    assert database.read_bytes() == before
    assert not (root / ".sqlite_copy_staging").exists()


@pytest.mark.parametrize("blocker", ["recent_clock", "conflicting_clock"])
def test_holding_clock_blocks_before_copy_intent(tmp_path, blocker):
    root, database = setup(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    if blocker == "recent_clock":
        state["queued"][FOLDER] = NOW.isoformat()
    else:
        state["first_seen"][FOLDER] = "2024-01-01T00:00:00"
    store.save_if_revision(state, revision)
    before = database.read_bytes()
    fetch, _ = transport([[item()]])
    with pytest.raises(RuntimeError, match="No collected lifecycle move candidate"):
        run(root, database, fetch)
    assert database.read_bytes() == before
    assert (root / "holding" / FOLDER / "payload").read_text() == "fixture"
    assert not (root / ".sqlite_copy_staging").exists()
