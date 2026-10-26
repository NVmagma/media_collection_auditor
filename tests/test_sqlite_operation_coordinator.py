"""Crash-safe intent tracking tests; no media operations are executed."""

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import (
    INTENTS_KEY, SQLiteOperationCoordinator,
)
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def _session(tmp_path):
    database = tmp_path / "state.db"
    write_offline_snapshot({section: {} for section in SECTIONS}, database)
    return database, RevisionedAuditSession(GuardedSQLiteStateStore(database))


def _reopen(database):
    return RevisionedAuditSession(GuardedSQLiteStateStore(database))


def test_intent_survives_restart_and_blocks_new_operation(tmp_path):
    database, session = _session(tmp_path)
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin("move-1", "move", {"source": "/media/Waiting/Movie"})
    restarted = _reopen(database)
    assert restarted.state[INTENTS_KEY]["phase"] == "intent_recorded"
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(restarted).begin(
            "move-2", "move", {"source": "/media/Waiting/Other"}
        )


def test_applied_phase_requires_explicit_reconciliation(tmp_path):
    database, session = _session(tmp_path)
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin("sync-1", "arr_sync", {"title": "Movie"})
    coordinator.mark_applied("sync-1")
    restarted = _reopen(database)
    assert restarted.state[INTENTS_KEY]["phase"] == "applied_pending_reconciliation"
    with pytest.raises(RuntimeError, match="blocked pending trusted verification"):
        SQLiteOperationCoordinator(restarted).reconcile("sync-1", restarted.state)
    with pytest.raises(RuntimeError, match="blocked pending trusted verification"):
        SQLiteOperationCoordinator(restarted).reconcile("sync-1", restarted.state | {
            INTENTS_KEY: {}
        })
    assert _reopen(database).state[INTENTS_KEY]["phase"] == "applied_pending_reconciliation"


def test_cannot_confirm_unrecorded_or_wrong_operation(tmp_path):
    _, session = _session(tmp_path)
    coordinator = SQLiteOperationCoordinator(session)
    with pytest.raises(RuntimeError, match="Missing"):
        coordinator.mark_applied("missing")
    coordinator.begin("move-1", "move", {"title": "Movie"})
    with pytest.raises(RuntimeError, match="mismatched"):
        coordinator.mark_applied("move-2")
    with pytest.raises(RuntimeError, match="not been confirmed"):
        coordinator.reconcile("move-1", session.state)


def test_invalid_intent_is_not_persisted(tmp_path):
    database, session = _session(tmp_path)
    coordinator = SQLiteOperationCoordinator(session)
    with pytest.raises(RuntimeError, match="Unsupported"):
        coordinator.begin("delete-1", "delete", {"title": "Movie"})
    with pytest.raises(RuntimeError, match="details"):
        coordinator.begin("move-1", "move", {})
    assert INTENTS_KEY not in _reopen(database).state


def test_pre_move_evidence_persists_across_restart(tmp_path):
    database, session = _session(tmp_path)
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin_move_with_evidence(
        "move-evidence-1", {"source": str(source), "destination": str(destination)}
    )
    pending = _reopen(database).state[INTENTS_KEY]
    assert pending["phase"] == "intent_recorded"
    assert pending["details"]["pre_move_evidence"]["version"] == 1
    assert pending["details"]["pre_move_evidence"]["fingerprint"]["status"] == "captured"
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(_reopen(database)).begin_move_with_evidence(
            "another", {"source": str(source), "destination": str(destination)}
        )


def test_pre_move_evidence_failure_never_persists_intent(tmp_path):
    database, session = _session(tmp_path)
    coordinator = SQLiteOperationCoordinator(session)
    with pytest.raises(RuntimeError, match="unavailable"):
        coordinator.begin_move_with_evidence(
            "move-evidence-2",
            {"source": str(tmp_path / "missing"),
             "destination": str(tmp_path / "destination")},
        )
    assert INTENTS_KEY not in _reopen(database).state


def test_pre_move_evidence_cannot_be_supplied_by_caller(tmp_path):
    database, session = _session(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(RuntimeError, match="Caller-supplied"):
        SQLiteOperationCoordinator(session).begin_move_with_evidence(
            "move-evidence-3",
            {"source": str(source), "destination": str(tmp_path / "dest"),
             "pre_move_evidence": {"version": 1}},
        )
    assert INTENTS_KEY not in _reopen(database).state


def test_pre_move_checkpoint_failure_cannot_create_durable_intent(tmp_path, monkeypatch):
    database, session = _session(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    def fail_checkpoint():
        raise RuntimeError("checkpoint interrupted")
    monkeypatch.setattr(session, "checkpoint", fail_checkpoint)
    with pytest.raises(RuntimeError, match="checkpoint interrupted"):
        SQLiteOperationCoordinator(session).begin_move_with_evidence(
            "move-evidence-4",
            {"source": str(source), "destination": str(tmp_path / "dest")},
        )
    assert INTENTS_KEY not in _reopen(database).state


def test_pre_move_evidence_does_not_enable_reconciliation(tmp_path):
    database, session = _session(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin_move_with_evidence(
        "move-evidence-5",
        {"source": str(source), "destination": str(tmp_path / "dest")},
    )
    coordinator.mark_applied("move-evidence-5")
    with pytest.raises(RuntimeError, match="blocked pending trusted verification"):
        SQLiteOperationCoordinator(_reopen(database)).reconcile(
            "move-evidence-5", _reopen(database).state,
        )
    assert _reopen(database).state[INTENTS_KEY]["phase"] == "applied_pending_reconciliation"


@pytest.mark.parametrize("crash_window", [
    "before_intent", "after_intent", "after_move", "after_applied",
])
def test_disposable_file_move_crash_windows_preserve_pending_state(
    tmp_path, crash_window,
):
    """Real rename of disposable test bytes; never production media or /lab."""
    import hashlib
    import os
    from scripts.sqlite_lab_fixture_guard import (
        FIXTURE_NAMES, inspect_disposable_destination_slot,
        verify_disposable_fixture_digest,
    )

    source = tmp_path / FIXTURE_NAMES[0]
    destination = tmp_path / FIXTURE_NAMES[1]
    payload = b"sqlite-disposable-crash-window-test-v1"
    source.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    database, session = _session(tmp_path)
    operation_id = "disposable-rehearsal-1"
    coordinator = SQLiteOperationCoordinator(session)

    if crash_window != "before_intent":
        assert inspect_disposable_destination_slot(destination, tmp_path)[
            "status"
        ] == "observed_unverified"
        # This rehearsal moves a disposable regular file, whereas
        # begin_move_with_evidence captures directory fingerprints only.
        # Record the durable intent without bypassing that safety contract.
        coordinator.begin(operation_id, "move", {
            "source": str(source), "destination": str(destination),
            "fixture_kind": "disposable_regular_file",
        })
    if crash_window in ("after_move", "after_applied"):
        # A real filesystem operation is deliberately restricted to tmp_path
        # fixtures created by this test; no media roots are ever referenced.
        os.rename(source, destination)
    if crash_window == "after_applied":
        coordinator.mark_applied(operation_id)

    restarted = _reopen(database)
    if crash_window == "before_intent":
        assert INTENTS_KEY not in restarted.state
        assert source.read_bytes() == payload
        assert not destination.exists()
        return

    phase = restarted.state[INTENTS_KEY]["phase"]
    assert phase == (
        "applied_pending_reconciliation" if crash_window == "after_applied"
        else "intent_recorded"
    )
    observed_path = destination if crash_window in (
        "after_move", "after_applied"
    ) else source
    assert verify_disposable_fixture_digest(
        observed_path, expected, tmp_path
    ) == {"status": "observed_unverified", "reason": "local_digest_matches"}
    assert not (source.exists() and destination.exists())
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(restarted).begin(
            "retry-blocked", "move", {"source": str(source)},
        )
    assert _reopen(database).state[INTENTS_KEY]["phase"] == phase
    if crash_window == "after_applied":
        with pytest.raises(RuntimeError, match="blocked pending trusted verification"):
            SQLiteOperationCoordinator(_reopen(database)).reconcile(
                operation_id, restarted.state,
            )


@pytest.mark.parametrize("disruption", ["both_present", "both_missing"])
def test_disposable_ambiguous_file_state_never_clears_intent(
    tmp_path, disruption,
):
    """Exercise ambiguous filesystem evidence without any cleanup/replay."""
    source = tmp_path / "sqlite_disposable_move_source.bin"
    destination = tmp_path / "sqlite_disposable_move_destination.bin"
    source.write_bytes(b"disposable-only")
    database, session = _session(tmp_path)
    SQLiteOperationCoordinator(session).begin(
        "ambiguous-1", "move",
        {"source": str(source), "destination": str(destination),
         "fixture_kind": "disposable_regular_file"},
    )
    if disruption == "both_present":
        destination.write_bytes(b"unrelated-disposable-file")
    else:
        source.unlink()
    restarted = _reopen(database)
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(restarted).begin(
            "unsafe-retry", "move", {"source": str(source)},
        )
    assert restarted.state[INTENTS_KEY]["phase"] == "intent_recorded"
    assert source.exists() == (disruption == "both_present")
    assert destination.exists() == (disruption == "both_present")


@pytest.mark.parametrize("window,expected", [
    ("intent_only", "source_only"),
    ("renamed_before_checkpoint", "destination_only_unverified"),
    ("applied_after_rename", "destination_only_unverified"),
    ("both_present", "both_present_ambiguous"),
    ("both_missing", "both_missing"),
])
def test_directory_rename_recovery_diagnostics_are_blocked_and_read_only(
    tmp_path, window, expected,
):
    """Integration of actual disposable directory rename, SQLite and diagnostics."""
    import os
    from app.sqlite_recovery_filesystem import inspect_pending_move_filesystem
    from app.sqlite_recovery_report import inspect_pending_recovery_status
    from app.state_store import GuardedSQLiteStateStore

    source = tmp_path / "disposable_source_directory"
    destination = tmp_path / "disposable_destination_directory"
    source.mkdir()
    (source / "marker.txt").write_bytes(b"disposable-directory-only")
    database, session = _session(tmp_path)
    coordinator = SQLiteOperationCoordinator(session)
    coordinator.begin_move_with_evidence("directory-move-1", {
        "source": str(source), "destination": str(destination),
    })

    if window in ("renamed_before_checkpoint", "applied_after_rename"):
        os.rename(source, destination)
    elif window == "both_present":
        destination.mkdir()
        (destination / "marker.txt").write_bytes(b"unrelated-disposable-bytes")
    elif window == "both_missing":
        # Remove only the disposable test marker and empty test directory.
        (source / "marker.txt").unlink()
        source.rmdir()
    if window == "applied_after_rename":
        coordinator.mark_applied("directory-move-1")

    before = GuardedSQLiteStateStore(database).load_with_revision()
    filesystem = inspect_pending_move_filesystem(database)
    recovery = inspect_pending_recovery_status(database)
    assert filesystem["interpretation"] == expected
    assert filesystem["status"] == "blocked"
    assert filesystem["authorization"] == "not_authorized"
    assert recovery["status"] == "blocked"
    assert recovery["storage_authority"] == "json"
    assert recovery["production_activation"] == "disabled"
    assert recovery["authorization"] == "blocked_pending_independent_verification"
    assert GuardedSQLiteStateStore(database).load_with_revision() == before
    assert _reopen(database).state[INTENTS_KEY]["phase"] == (
        "applied_pending_reconciliation"
        if window == "applied_after_rename" else "intent_recorded"
    )
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(_reopen(database)).begin(
            "unsafe-retry", "move", {"source": str(source)},
        )
    if window in ("renamed_before_checkpoint", "applied_after_rename"):
        assert (destination / "marker.txt").read_bytes() == b"disposable-directory-only"
        assert not source.exists()


@pytest.mark.parametrize("window,expected_phase,expected_location", [
    ("after_intent", "intent_recorded", "source_only"),
    ("after_rename", "intent_recorded", "destination_only_unverified"),
    ("after_applied", "applied_pending_reconciliation", "destination_only_unverified"),
])
def test_disposable_directory_move_survives_separate_process_exit(
    tmp_path, window, expected_phase, expected_location,
):
    """Run a worker in a fresh interpreter, exit, then inspect independently.

    The worker can only rename directories created by this test under tmp_path.
    No network, production mounts, or cleanup of production data is involved.
    """
    import json
    import os
    import subprocess
    import sys
    from app.sqlite_recovery_filesystem import inspect_pending_move_filesystem
    from app.sqlite_recovery_report import inspect_pending_recovery_status
    from app.state_store import GuardedSQLiteStateStore

    source = tmp_path / "disposable_source_directory"
    destination = tmp_path / "disposable_destination_directory"
    source.mkdir()
    (source / "marker.txt").write_bytes(b"isolated-worker-test")
    database, _ = _session(tmp_path)
    worker = """
import os
import sys
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.state_store import GuardedSQLiteStateStore
db, source, destination, window = sys.argv[1:]
coordinator = SQLiteOperationCoordinator(
    RevisionedAuditSession(GuardedSQLiteStateStore(db))
)
coordinator.begin_move_with_evidence(
    "isolated-worker-1", {"source": source, "destination": destination}
)
if window != "after_intent":
    os.rename(source, destination)
if window == "after_applied":
    coordinator.mark_applied("isolated-worker-1")
"""
    from pathlib import Path
    repository_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository_root)
    completed = subprocess.run(
        [sys.executable, "-c", worker, str(database), str(source),
         str(destination), window],
        cwd=repository_root, env=environment, capture_output=True,
        text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    before = GuardedSQLiteStateStore(database).load_with_revision()
    filesystem = inspect_pending_move_filesystem(database)
    report = inspect_pending_recovery_status(database)
    assert filesystem["interpretation"] == expected_location
    assert filesystem["authorization"] == "not_authorized"
    assert report["status"] == "blocked"
    assert report["operation_phase"] == expected_phase
    assert report["storage_authority"] == "json"
    assert GuardedSQLiteStateStore(database).load_with_revision() == before
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(_reopen(database)).begin(
            "unsafe-second-worker", "move", {"source": str(source)}
        )
    if window != "after_intent":
        assert (destination / "marker.txt").read_bytes() == b"isolated-worker-test"


@pytest.mark.parametrize("window,expected_phase,expected_location", [
    ("after_intent", "intent_recorded", "source_only"),
    ("after_rename", "intent_recorded", "destination_only_unverified"),
    ("after_applied", "applied_pending_reconciliation", "destination_only_unverified"),
])
def test_sigkill_disposable_directory_worker_preserves_recovery_block(
    tmp_path, window, expected_phase, expected_location,
):
    """Force-kill a separate worker after a durable checkpoint or rename.

    SIGKILL is deliberately sent only to the child Python interpreter.
    All filesystem effects are limited to pytest's disposable tmp_path.
    """
    import os
    import signal
    import subprocess
    import sys
    from pathlib import Path
    from app.sqlite_recovery_filesystem import inspect_pending_move_filesystem
    from app.sqlite_recovery_report import inspect_pending_recovery_status
    from app.state_store import GuardedSQLiteStateStore

    if os.name != "posix" or not hasattr(signal, "SIGKILL"):
        pytest.skip("SIGKILL rehearsal requires POSIX")
    source = tmp_path / "sigkill_disposable_source"
    destination = tmp_path / "sigkill_disposable_destination"
    source.mkdir()
    (source / "marker.txt").write_bytes(b"sigkill-disposable-only")
    database, _ = _session(tmp_path)
    worker = """
import os
import signal
import sys
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.state_store import GuardedSQLiteStateStore
db, src, dst, window = sys.argv[1:]
coordinator = SQLiteOperationCoordinator(
    RevisionedAuditSession(GuardedSQLiteStateStore(db))
)
coordinator.begin_move_with_evidence(
    "sigkill-rehearsal-1", {"source": src, "destination": dst}
)
if window != "after_intent":
    os.rename(src, dst)
if window == "after_applied":
    coordinator.mark_applied("sigkill-rehearsal-1")
os.kill(os.getpid(), signal.SIGKILL)
"""
    repository_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repository_root)
    completed = subprocess.run(
        [sys.executable, "-c", worker, str(database), str(source),
         str(destination), window],
        cwd=repository_root, env=env, capture_output=True,
        text=True, timeout=30, check=False,
    )
    assert completed.returncode == -signal.SIGKILL, completed.stderr
    before = GuardedSQLiteStateStore(database).load_with_revision()
    filesystem = inspect_pending_move_filesystem(database)
    recovery = inspect_pending_recovery_status(database)
    assert filesystem["interpretation"] == expected_location
    assert filesystem["authorization"] == "not_authorized"
    assert recovery["status"] == "blocked"
    assert recovery["operation_phase"] == expected_phase
    assert recovery["storage_authority"] == "json"
    assert GuardedSQLiteStateStore(database).load_with_revision() == before
    with pytest.raises(RuntimeError, match="Unresolved"):
        SQLiteOperationCoordinator(_reopen(database)).begin(
            "unsafe-retry", "move", {"source": str(source)}
        )
    if window != "after_intent":
        assert (destination / "marker.txt").read_bytes() == b"sigkill-disposable-only"
