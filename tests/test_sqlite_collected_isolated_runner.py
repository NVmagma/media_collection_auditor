"""Live-collection runner with fake GET transport and disposable state only."""
from datetime import datetime
import sys

import pytest

from app.sqlite_collected_isolated_runner import run_collected_isolated_move
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

NOW = datetime(2026, 1, 1)
FOLDER = "Collected Movie"
LIMITS = {"Waiting": 7, "Holding": 7, "Removal": 7, "Keep": 0}


def lab(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    for stage in ("transient", "holding", "removal", "keep"):
        (root / stage).mkdir()
    (root / "transient" / FOLDER).mkdir()
    (root / "transient" / FOLDER / "payload").write_text("fixture")
    state = {section: {} for section in SECTIONS}
    state["first_seen"][FOLDER] = "2024-01-01T00:00:00"
    database = root / "state.db"
    write_offline_snapshot(state, database)
    return root, database


def item(tags=None, identity="same", favorite=False):
    return {"Id": identity, "Type": "Movie", "Path": "/media/" + FOLDER + "/movie.mkv",
            "Tags": tags or [], "UserData": {"Played": False, "PlayCount": 0,
                                               "IsFavorite": favorite}}


def transport(scans):
    calls = []
    scan = -1
    def fetch(path, params):
        nonlocal scan
        calls.append(path)
        if path == "/Users":
            scan += 1
            return [{"Id": "user"}]
        records = scans[min(scan, len(scans) - 1)]
        if isinstance(records, Exception):
            raise records
        return {"TotalRecordCount": len(records), "Items": records}
    return fetch, calls


def run(root, database, fetch, **kwargs):
    return run_collected_isolated_move(
        root=root, database=database, operation_id="collected", media_key=FOLDER,
        title_folder=FOLDER, jellyfin_type="Movie", thresholds=LIMITS,
        fetch=fetch, clock=lambda: NOW, **kwargs)


def assert_unchanged(root, database, before):
    assert database.read_bytes() == before
    assert (root / "transient" / FOLDER / "payload").read_text() == "fixture"
    assert not (root / "holding" / FOLDER).exists()
    assert not (root / "keep" / FOLDER).exists()


@pytest.mark.parametrize("refresh", [
    [item(["keep-forever"])], [item(favorite=True)], [item(identity="replacement")], [],
    RuntimeError("private-server-error"),
])
def test_refresh_change_or_failure_stops_before_intent(tmp_path, refresh):
    root, database = lab(tmp_path)
    before = database.read_bytes()
    fetch, calls = transport([[item()], refresh])
    with pytest.raises(RuntimeError, match="replan required|unambiguous"):
        run(root, database, fetch)
    assert_unchanged(root, database, before)
    assert calls.count("/Users") == 2


def test_initial_missing_observation_stops_without_second_scan(tmp_path):
    root, database = lab(tmp_path)
    before = database.read_bytes()
    fetch, calls = transport([[]])
    with pytest.raises(RuntimeError, match="unambiguous"):
        run(root, database, fetch)
    assert_unchanged(root, database, before)
    assert calls.count("/Users") == 1


@pytest.mark.parametrize("ticks", [[0, 61], [0, 0, 0, 61], [0, -1]])
def test_expiry_or_timer_reversal_stops_before_intent(tmp_path, ticks):
    root, database = lab(tmp_path)
    before = database.read_bytes()
    values = iter(ticks)
    fetch, _ = transport([[item()]])
    with pytest.raises(RuntimeError, match="window expired"):
        run(root, database, fetch, timer=lambda: next(values))
    assert_unchanged(root, database, before)


def test_pending_operation_precedes_network(tmp_path):
    root, database = lab(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state["sqlite_pending_operations"] = {"id": "old"}
    store.save_if_revision(state, revision)
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="Unresolved"):
        run(root, database, lambda *args: pytest.fail("no network permitted"))
    assert_unchanged(root, database, before)


def test_both_scans_complete_before_durable_intent(tmp_path):
    root, database = lab(tmp_path)
    fetch, calls = transport([[item()]])
    with pytest.raises(RuntimeError, match="Injected crash after intent"):
        run(root, database, fetch, fault_at="after_intent")
    assert calls.count("/Users") == 2
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert state["sqlite_pending_operations"]["details"]["media_key"] == FOLDER
    assert FOLDER in state["first_seen"]
    assert (root / "transient" / FOLDER).is_dir()


@pytest.mark.skipif(sys.platform != "linux", reason="Atomic no-replace rename requires Linux")
@pytest.mark.parametrize("protected,target", [(False, "holding"), (True, "keep")])
def test_unchanged_collected_protection_drives_disposable_candidate(tmp_path, protected, target):
    root, database = lab(tmp_path)
    fetch, calls = transport([[item(["keep-forever"] if protected else [])]])
    result = run(root, database, fetch)
    assert result["status"] == "disposable_reconciled"
    assert calls.count("/Users") == 2
    assert (root / target / FOLDER / "payload").read_text() == "fixture"
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert "sqlite_pending_operations" not in state
    assert FOLDER in state["keep_seen" if protected else "queued"]


def test_concurrent_state_change_during_refresh_prevents_intent(tmp_path):
    root, database = lab(tmp_path)
    fetch, calls = transport([[item()]])
    scans = 0
    def changing_fetch(path, params):
        nonlocal scans
        if path == "/Users":
            scans += 1
            if scans == 2:
                store = GuardedSQLiteStateStore(database)
                state, revision = store.load_with_revision()
                state["concurrent"] = {"changed": True}
                store.save_if_revision(state, revision)
        return fetch(path, params)
    with pytest.raises(RuntimeError):
        run(root, database, changing_fetch)
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert "sqlite_pending_operations" not in state
    assert state["concurrent"] == {"changed": True}
    assert FOLDER in state["first_seen"]
    assert (root / "transient" / FOLDER).is_dir()
    assert not (root / "holding" / FOLDER).exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Atomic no-replace rename requires Linux")
def test_collected_move_queues_arr_atomically_then_delivers_once(tmp_path):
    from app.sqlite_isolated_arr_runner import deliver_isolated_arr_request
    root, database = lab(tmp_path)
    fetch, _ = transport([[item(["keep-forever"])]])
    request = {"service": "radarr", "title_id": 42, "root": "/arr/keep", "monitored": False}
    run(root, database, fetch, arr_sync_request=request)
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert state["keep_seen"][FOLDER] == NOW.isoformat()
    assert state["arr_sync_pending"][FOLDER] == {"stage": "keep", **request}
    assert "sqlite_pending_operations" not in state
    calls = []
    result = deliver_isolated_arr_request(
        root=root, database=database, operation_id="arr", media_key=FOLDER,
        title_folder=FOLDER, details=request, send=lambda details: calls.append(details) or True)
    assert result["outcome"] == "acknowledged_unverified"
    assert len(calls) == 1
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert state["sqlite_pending_operations"]["kind"] == "arr_sync"
    assert FOLDER in state["arr_sync_pending"]
