"""Live-witness copy completion retains original bytes and atomic state history."""
import errno
import sys
import pytest
from tests.test_sqlite_collected_isolated_runner import lab, item, transport, NOW, FOLDER, LIMITS
from app.sqlite_collected_isolated_runner import run_collected_isolated_copy_completion
from app.sqlite_disposable_copy_inspection import inspect_disposable_copy
from app.state_store import GuardedSQLiteStateStore

REQUEST = {"service": "radarr", "title_id": 42, "root": "/fixture/holding", "monitored": False}


def run(root, database, fetch, **kwargs):
    return run_collected_isolated_copy_completion(root=root, database=database,
        operation_id="complete-copy", media_key=FOLDER, title_folder=FOLDER,
        jellyfin_type="Movie", thresholds=LIMITS, fetch=fetch, clock=lambda: NOW,
        arr_sync_request=REQUEST, **kwargs)


def test_real_capability_preserves_original_bytes_in_all_supported_outcomes(tmp_path):
    root, database = lab(tmp_path)
    fetch, _ = transport([[item()]])
    try:
        result = run(root, database, fetch)
    except RuntimeError as exc:
        if sys.platform != "linux":
            assert str(exc) == "Atomic no-replace rename requires Linux"
        else:
            assert str(exc) == "Atomic no-replace rename unsupported"
            assert isinstance(exc.__cause__, OSError)
            assert exc.__cause__.errno in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP)
        assert (root / "transient" / FOLDER / "payload").read_text() == "fixture"
        state = GuardedSQLiteStateStore(database).load_with_revision()[0]
        assert "sqlite_pending_operations" in state and not state["arr_sync_pending"]
    else:
        assert result["lifecycle_committed"] and result["original_bytes_retained"]
        assert (root / ".sqlite_retained_sources" / "complete-copy" / "payload").read_text() == "fixture"
        assert not (root / "transient" / FOLDER).exists()
        state = GuardedSQLiteStateStore(database).load_with_revision()[0]
        assert state["queued"][FOLDER] == NOW.isoformat()
        assert state["arr_sync_pending"][FOLDER]["title_id"] == 42
        assert "sqlite_pending_operations" not in state


@pytest.mark.skipif(sys.platform != "linux", reason="Actual Linux publication/quarantine required")
@pytest.mark.parametrize("fault,cleared,retired", [(None, True, True),
    ("after_retirement_intent", False, False), ("after_source_quarantine", False, True),
    ("after_completion_checkpoint", True, True)])
def test_actual_completion_and_crashes_never_drop_source_bytes(tmp_path, fault, cleared, retired):
    root, database = lab(tmp_path)
    fetch, calls = transport([[item()]])
    if fault:
        with pytest.raises(RuntimeError, match="Injected completion crash"):
            run(root, database, fetch, completion_fault_at=fault)
    else:
        report = run(root, database, fetch)
        assert report["status"] == "disposable_copy_reconciled_source_quarantined"
        assert not report["permanent_deletion_performed"]
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert ("sqlite_pending_operations" not in state) is cleared
    assert (FOLDER in state["queued"]) is cleared
    assert (FOLDER in state["first_seen"]) is not cleared
    assert (FOLDER in state["arr_sync_pending"]) is cleared
    original = root / ".sqlite_retained_sources" / "complete-copy" if retired else root / "transient" / FOLDER
    assert (original / "payload").read_text() == "fixture"
    assert (root / "holding" / FOLDER / "payload").read_text() == "fixture"
    assert calls.count("/Users") == 5
    if not cleared:
        report = inspect_disposable_copy(root=root)
        assert report["status"] == "blocked"
        assert report["retained_source_status"] == ("content_matches_unverified" if retired else "missing")
        with pytest.raises(RuntimeError, match="Unresolved"):
            run(root, database, lambda *args: pytest.fail("never replay pending completion"))
    else:
        assert state["sqlite_retained_sources"]["complete-copy"]["media_key"] == FOLDER


@pytest.mark.skipif(sys.platform != "linux", reason="Actual Linux completion transaction required")
@pytest.mark.parametrize("committed", [False, True])
def test_final_checkpoint_uncertainty_preserves_all_or_nothing_tracking(tmp_path, monkeypatch, committed):
    root, database = lab(tmp_path)
    original = GuardedSQLiteStateStore.save_if_revision
    writes = 0
    def save(self, state, revision):
        nonlocal writes
        writes += 1
        if writes == 6:
            if committed:
                original(self, state, revision)
            raise RuntimeError("injected completion checkpoint uncertainty")
        return original(self, state, revision)
    monkeypatch.setattr(GuardedSQLiteStateStore, "save_if_revision", save)
    fetch, _ = transport([[item()]])
    with pytest.raises(RuntimeError, match="checkpoint uncertainty"):
        run(root, database, fetch)
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert ("sqlite_pending_operations" not in state) is committed
    assert (FOLDER in state["queued"]) is committed
    assert (FOLDER in state["arr_sync_pending"]) is committed
    assert ("complete-copy" in state.get("sqlite_retained_sources", {})) is committed
    assert (root / ".sqlite_retained_sources" / "complete-copy" / "payload").read_text() == "fixture"
    assert (root / "holding" / FOLDER / "payload").read_text() == "fixture"


def test_changed_refresh_blocks_before_publication_and_quarantine(tmp_path):
    root, database = lab(tmp_path)
    fetch, _ = transport([[item()], [item()], [item(["keep-forever"])]])
    with pytest.raises(RuntimeError, match="changed"):
        run(root, database, fetch)
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert "publication" not in state["sqlite_pending_operations"]["details"]
    assert not state["queued"] and not state["arr_sync_pending"]
    assert (root / "transient" / FOLDER / "payload").read_text() == "fixture"


@pytest.mark.skipif(sys.platform != "linux", reason="Actual publication before final fresh check required")
def test_protection_change_before_quarantine_retains_public_source(tmp_path):
    root, database = lab(tmp_path)
    fetch, calls = transport([[item()], [item()], [item()], [item()], [item(["keep-forever"])]])
    with pytest.raises(RuntimeError, match="changed"):
        run(root, database, fetch)
    assert calls.count("/Users") == 5
    assert (root / "transient" / FOLDER / "payload").read_text() == "fixture"
    assert (root / "holding" / FOLDER / "payload").read_text() == "fixture"
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert FOLDER in state["first_seen"] and not state["queued"] and not state["arr_sync_pending"]
    assert "retirement" not in state["sqlite_pending_operations"]["details"]


@pytest.mark.skipif(sys.platform != "linux", reason="Actual no-overwrite source quarantine race required")
def test_concurrent_archive_destination_is_never_overwritten(tmp_path, monkeypatch):
    import app.sqlite_disposable_copy_completion as module
    root, database = lab(tmp_path)
    original = module.rename_directory_noreplace_at
    def race(source_fd, name, archive_fd, operation):
        slot = root / ".sqlite_retained_sources" / operation
        slot.mkdir()
        (slot / "preserved").write_text("external archive")
        return original(source_fd, name, archive_fd, operation)
    monkeypatch.setattr(module, "rename_directory_noreplace_at", race)
    fetch, _ = transport([[item()]])
    with pytest.raises(FileExistsError):
        run(root, database, fetch)
    assert (root / "transient" / FOLDER / "payload").read_text() == "fixture"
    assert (root / ".sqlite_retained_sources" / "complete-copy" / "preserved").read_text() == "external archive"
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert FOLDER in state["first_seen"] and not state["queued"]
    assert state["sqlite_pending_operations"]["details"]["retirement"]["phase"] == "prepared"


@pytest.mark.skipif(sys.platform != "linux", reason="Actual whole-show completion required")
def test_whole_show_completion_retains_every_original_season(tmp_path):
    from tests.test_sqlite_collected_copy_series import setup, series, KEY
    root, database = setup(tmp_path)
    fetch, calls = transport([[series()]])
    result = run_collected_isolated_copy_completion(root=root, database=database,
        operation_id="series-complete", media_key=KEY, title_folder=FOLDER,
        jellyfin_type="Series", thresholds=LIMITS, fetch=fetch, clock=lambda: NOW,
        arr_sync_request={"service": "sonarr", "title_id": 99, "root": "/fixture/tv_hold", "monitored": True})
    assert result["original_bytes_retained"] and calls.count("/Users") == 5
    for parent in (root / "holding" / FOLDER, root / ".sqlite_retained_sources" / "series-complete"):
        for season in ("Season 00", "Season 01", "Season 02"):
            assert (parent / season / "episode.mkv").read_bytes() == b"disposable episode"
        assert (parent / "Empty Season").is_dir()
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert KEY in state["queued"] and KEY not in state["first_seen"]
    assert state["arr_sync_pending"][KEY]["service"] == "sonarr"
    assert "sqlite_pending_operations" not in state


@pytest.mark.skipif(sys.platform != "linux", reason="Actual copy completion and Arr handoff required")
def test_completed_copy_hands_atomic_queue_to_arr_delivery_and_readback(tmp_path):
    from datetime import datetime, timezone
    from app.sqlite_isolated_arr_runner import deliver_isolated_arr_request
    from app.sqlite_isolated_arr_inspection import inspect_isolated_arr_outcome
    root, database = lab(tmp_path)
    fetch, _ = transport([[item()]])
    run(root, database, fetch)
    sends = []
    result = deliver_isolated_arr_request(root=root, database=database,
        operation_id="arr-after-copy", media_key=FOLDER, title_folder=FOLDER,
        details=REQUEST, send=lambda details: sends.append(details) or True)
    assert result["outcome"] == "acknowledged_unverified" and len(sends) == 1
    def readback(service, title_id):
        return {"service": service, "title_id": str(title_id),
                "observed_at": datetime.now(timezone.utc),
                "data": {"id": title_id, "path": REQUEST["root"] + "/" + FOLDER, "monitored": False}}
    report = inspect_isolated_arr_outcome(root=root, fetch=readback)
    assert report["observation"] == "matching_record_unverified"
    assert not report["clearance_authorized"] and not report["retry_authorized"]
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert state["sqlite_pending_operations"]["kind"] == "arr_sync"
    assert state["arr_sync_pending"][FOLDER]["title_id"] == 42
    assert (root / ".sqlite_retained_sources" / "complete-copy" / "payload").read_text() == "fixture"


def test_invalid_queue_request_stops_before_copy_intent(tmp_path):
    root, database = lab(tmp_path)
    before = database.read_bytes()
    fetch, _ = transport([[item()]])
    with pytest.raises(RuntimeError, match="positive integer"):
        run_collected_isolated_copy_completion(root=root, database=database,
            operation_id="invalid-request", media_key=FOLDER, title_folder=FOLDER,
            jellyfin_type="Movie", thresholds=LIMITS, fetch=fetch, clock=lambda: NOW,
            arr_sync_request={**REQUEST, "title_id": True})
    assert database.read_bytes() == before
    assert not (root / ".sqlite_copy_staging").exists()


def test_reused_retention_identifier_stops_before_publication(tmp_path):
    from app.sqlite_audit_session import RevisionedAuditSession
    root, database = lab(tmp_path)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    session.state["sqlite_retained_sources"] = {"complete-copy": {"preserve": "older original"}}
    session.checkpoint()
    fetch, _ = transport([[item()]])
    with pytest.raises(RuntimeError, match="already recorded"):
        run(root, database, fetch)
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert state["sqlite_retained_sources"]["complete-copy"] == {"preserve": "older original"}
    assert "publication" not in state["sqlite_pending_operations"]["details"]
    assert not (root / "holding" / FOLDER).exists()
    assert (root / "transient" / FOLDER / "payload").read_text() == "fixture"


@pytest.mark.parametrize("scenario", ["long_transfer", "changed", "changed_second_scan", "slow_refresh", "timer_reversed", "clock_reversed"])
def test_transfer_renewal_requires_fresh_unchanged_bounded_observations(tmp_path, monkeypatch, scenario):
    from datetime import timedelta
    import app.sqlite_disposable_copy_stage as stage
    root, database = lab(tmp_path)
    elapsed = 0
    original = stage._stage_copy
    def long_stage(**kwargs):
        nonlocal elapsed
        result = original(**kwargs)
        elapsed = -1 if scenario in ("timer_reversed", "clock_reversed") else 600
        return result
    monkeypatch.setattr(stage, "_stage_copy", long_stage)
    base_fetch, calls = transport([[item()], [item()],
        [item(["keep-forever"])] if scenario == "changed" else [item()],
        [item(["keep-forever"])] if scenario == "changed_second_scan" else [item()]])
    def fetch(*args, **kwargs):
        nonlocal elapsed
        response = base_fetch(*args, **kwargs)
        if scenario == "slow_refresh" and calls.count("/Users") >= 3:
            elapsed += 61
        return response
    def invoke():
        return run_collected_isolated_copy_completion(root=root, database=database,
            operation_id="complete-copy", media_key=FOLDER, title_folder=FOLDER,
            jellyfin_type="Movie", thresholds=LIMITS, fetch=fetch,
            clock=lambda: NOW + timedelta(seconds=elapsed if scenario != "timer_reversed" else 0),
            timer=lambda: elapsed if scenario != "clock_reversed" else 0)
    if scenario == "long_transfer":
        try:
            report = invoke()
        except RuntimeError as exc:
            assert str(exc) in ("Atomic no-replace rename requires Linux", "Atomic no-replace rename unsupported")
            state = GuardedSQLiteStateStore(database).load_with_revision()[0]
            assert state["sqlite_pending_operations"]["details"]["publication"]["phase"] == "prepared"
            assert calls.count("/Users") == 4
        else:
            assert report["lifecycle_committed"] and report["original_bytes_retained"]
            assert calls.count("/Users") == 5
        return
    with pytest.raises(RuntimeError, match="changed" if scenario in ("changed", "changed_second_scan") else "window expired"):
        invoke()
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert "publication" not in state["sqlite_pending_operations"]["details"]
    assert FOLDER in state["first_seen"] and not state["queued"]
    assert (root / "transient" / FOLDER / "payload").read_text() == "fixture"
    assert not (root / "holding" / FOLDER).exists()


@pytest.mark.parametrize("boundary", ["publication", "quarantine"])
def test_checkpoint_delay_expires_before_directory_action(tmp_path, monkeypatch, boundary):
    if boundary == "quarantine" and sys.platform != "linux":
        pytest.skip("Actual Linux publication required before quarantine guard")
    root, database = lab(tmp_path)
    elapsed = 0
    writes = 0
    original = GuardedSQLiteStateStore.save_if_revision
    def delayed_checkpoint(self, state, revision):
        nonlocal elapsed, writes
        result = original(self, state, revision)
        writes += 1
        if writes == (3 if boundary == "publication" else 5):
            elapsed = 61
        return result
    monkeypatch.setattr(GuardedSQLiteStateStore, "save_if_revision", delayed_checkpoint)
    fetch, _ = transport([[item()]])
    with pytest.raises(RuntimeError, match="window expired"):
        run(root, database, fetch, timer=lambda: elapsed)
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    details = state["sqlite_pending_operations"]["details"]
    assert details["publication"]["phase"] == ("prepared" if boundary == "publication" else "published_source_retained")
    assert (root / "transient" / FOLDER / "payload").read_text() == "fixture"
    assert not (root / ".sqlite_retained_sources" / "complete-copy").exists()
    assert FOLDER in state["first_seen"] and not state["queued"] and not state["arr_sync_pending"]
