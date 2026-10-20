"""Two-scan Jellyfin parity for portable staging, never production execution."""
import pytest
from tests.test_sqlite_collected_isolated_runner import lab, item, transport, NOW, FOLDER, LIMITS
from app.sqlite_collected_isolated_runner import run_collected_isolated_copy
from app.state_store import GuardedSQLiteStateStore


def run(root, database, fetch, **kwargs):
    return run_collected_isolated_copy(root=root, database=database,
        operation_id="collected-copy", media_key=FOLDER, title_folder=FOLDER,
        jellyfin_type="Movie", thresholds=LIMITS, fetch=fetch, clock=lambda: NOW, **kwargs)


def test_two_complete_scans_stage_source_retaining_copy(tmp_path):
    root, database = lab(tmp_path)
    fetch, calls = transport([[item()]])
    report = run(root, database, fetch)
    assert calls.count("/Users") == 2
    assert report["source_retained"] and not report["lifecycle_committed"]
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    pending = state["sqlite_pending_operations"]
    assert pending["details"]["plan_binding"]["destination_stage"] == "holding"
    assert pending["details"]["copy_phase"] == "verified_source_retained"
    assert FOLDER in state["first_seen"] and not state["queued"] and not state["arr_sync_pending"]
    assert (root / "transient" / FOLDER / "payload").read_text() == "fixture"


@pytest.mark.parametrize("refresh", [[item(["keep-forever"])], [item(favorite=True)],
    [item(identity="replacement")], [], RuntimeError("private service failure")])
def test_changed_or_incomplete_refresh_stops_before_intent(tmp_path, refresh):
    root, database = lab(tmp_path)
    before = database.read_bytes()
    fetch, calls = transport([[item()], refresh])
    with pytest.raises(RuntimeError, match="replan required|unambiguous"):
        run(root, database, fetch)
    assert calls.count("/Users") == 2
    assert database.read_bytes() == before
    assert not (root / ".sqlite_copy_staging").exists()


@pytest.mark.parametrize("values", [[0, 61], [0, 0, 0, 0, 61]])
def test_expired_scan_stops_before_intent(tmp_path, values):
    root, database = lab(tmp_path)
    before = database.read_bytes()
    fetch, _ = transport([[item()]])
    ticks = iter(values)
    with pytest.raises(RuntimeError, match="window expired"):
        run(root, database, fetch, timer=lambda: next(ticks))
    assert database.read_bytes() == before
    assert not (root / ".sqlite_copy_staging").exists()


def test_pending_copy_prevents_network_and_replay(tmp_path):
    root, database = lab(tmp_path)
    fetch, _ = transport([[item()]])
    run(root, database, fetch)
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="Unresolved"):
        run(root, database, lambda *args: pytest.fail("pending intent precedes network"))
    assert database.read_bytes() == before
