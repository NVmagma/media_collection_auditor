"""Cross-process ownership and pending-intent precedence for isolated execution."""
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys

import pytest

import app.sqlite_isolated_lifecycle_runner as module
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def lab(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    for stage in ("transient", "holding", "removal", "keep"):
        (root / stage).mkdir()
    (root / "transient" / "Movie").mkdir()
    (root / "transient" / "Movie" / "fixture.txt").write_text("disposable media")
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["Movie"] = "2024-01-01T00:00:00"
    database = root / "state.db"
    write_offline_snapshot(state, database)
    return root, database


def run(root, database, **kwargs):
    return module.run_isolated_lifecycle_move(
        root=root, database=database, operation_id="move-one", media_key="Movie",
        observed_at=datetime(2026, 1, 1), **kwargs)


def test_other_process_cannot_enter_and_lock_is_reusable(tmp_path):
    root, database = lab(tmp_path)
    before = database.read_bytes()
    code = """
import sys
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
try:
    with isolated_runner_lock(sys.argv[1]):
        sys.exit(7)
except RuntimeError as exc:
    sys.exit(0 if str(exc) == 'Another isolated SQLite runner is active' else 8)
"""
    with module.isolated_runner_lock(root):
        result = subprocess.run([sys.executable, "-c", code, str(root)],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
    with module.isolated_runner_lock(root):
        pass
    assert database.read_bytes() == before
    assert (root / ".sqlite_runner.lock").is_file()


def test_pending_intent_stops_before_executor(tmp_path, monkeypatch):
    root, database = lab(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state["sqlite_pending_operations"] = {"id": "old", "phase": "intent_recorded"}
    store.save_if_revision(state, revision)
    before = database.read_bytes()
    monkeypatch.setattr(module, "execute_disposable_lifecycle_move",
                        lambda **kwargs: pytest.fail("executor must not run"))
    with pytest.raises(RuntimeError, match="Unresolved"):
        run(root, database)
    assert database.read_bytes() == before
    assert (root / "transient" / "Movie").is_dir()


def test_stale_revision_stops_before_executor(tmp_path, monkeypatch):
    root, database = lab(tmp_path)
    monkeypatch.setattr(module, "execute_disposable_lifecycle_move",
                        lambda **kwargs: pytest.fail("executor must not run"))
    with pytest.raises(RuntimeError, match="Stale"):
        run(root, database, expected_revision=4)


def test_lock_released_after_failure(tmp_path):
    root, _ = lab(tmp_path)
    with pytest.raises(ValueError):
        with module.isolated_runner_lock(root):
            raise ValueError("injected")
    with module.isolated_runner_lock(root):
        pass


def test_symlink_lock_rejected_without_changing_target(tmp_path):
    root, _ = lab(tmp_path)
    target = tmp_path / "unrelated"
    target.write_text("preserve")
    (root / ".sqlite_runner.lock").symlink_to(target)
    with pytest.raises(OSError):
        with module.isolated_runner_lock(root):
            pytest.fail("unsafe lock accepted")
    assert target.read_text() == "preserve"


def test_unmarked_root_rejected_without_creating_lock(tmp_path):
    root, database = lab(tmp_path)
    (root / ".sqlite_disposable_rehearsal").unlink()
    with pytest.raises(RuntimeError, match="Marked disposable"):
        run(root, database)
    assert not (root / ".sqlite_runner.lock").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Atomic no-replace rename requires Linux")
def test_runner_completes_only_disposable_witnessed_move(tmp_path):
    root, database = lab(tmp_path)
    result = run(root, database)
    assert result["status"] == "disposable_reconciled"
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert "Movie" not in state["first_seen"]
    assert state["queued"]["Movie"] == "2026-01-01T00:00:00"
    assert "sqlite_pending_operations" not in state
    assert (root / "holding" / "Movie" / "fixture.txt").read_text() == "disposable media"


@pytest.mark.skipif(sys.platform != "linux", reason="Atomic no-replace rename requires Linux")
def test_crash_retains_intent_and_next_runner_refuses_replay(tmp_path):
    root, database = lab(tmp_path)
    with pytest.raises(RuntimeError, match="Injected crash after rename"):
        run(root, database, fault_at="after_rename")
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="Unresolved"):
        run(root, database)
    assert database.read_bytes() == before
    assert (root / "holding" / "Movie").is_dir()


def test_runner_holds_lock_through_executor_failure(tmp_path, monkeypatch):
    root, database = lab(tmp_path)
    def executor(**kwargs):
        with pytest.raises(RuntimeError, match="Another isolated"):
            with module.isolated_runner_lock(root):
                pytest.fail("second runner entered during execution")
        raise RuntimeError("injected executor failure")
    monkeypatch.setattr(module, "execute_disposable_lifecycle_move", executor)
    with pytest.raises(RuntimeError, match="injected executor"):
        run(root, database)
    with module.isolated_runner_lock(root):
        pass


def test_hardlinked_lock_is_rejected(tmp_path):
    root, _ = lab(tmp_path)
    target = tmp_path / "unrelated"
    target.write_text("preserve")
    os.link(target, root / ".sqlite_runner.lock")
    with pytest.raises(RuntimeError, match="Unsafe disposable runner lock"):
        with module.isolated_runner_lock(root):
            pytest.fail("unsafe lock accepted")
    assert target.read_text() == "preserve"


def test_different_database_is_rejected_before_lock_creation(tmp_path):
    root, _ = lab(tmp_path)
    with pytest.raises(RuntimeError, match="binding mismatch"):
        run(root, tmp_path / "other.db")
    assert not (root / ".sqlite_runner.lock").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Atomic no-replace rename requires Linux")
@pytest.mark.parametrize("stage", ["transient", "holding"])
def test_parent_replacement_at_syscall_does_not_redirect_and_retains_intent(tmp_path, monkeypatch, stage):
    import app.sqlite_disposable_lifecycle_flow as flow
    root, database = lab(tmp_path)
    actual = flow.rename_directory_noreplace_at
    def racing_rename(*args):
        (root / stage).rename(root / ("original_" + stage))
        (root / stage).mkdir()
        (root / stage / "Movie").mkdir()
        (root / stage / "Movie" / "fixture.txt").write_text("unrelated")
        actual(*args)
    monkeypatch.setattr(flow, "rename_directory_noreplace_at", racing_rename)
    with pytest.raises(RuntimeError, match="stage directory changed"):
        run(root, database)
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert "sqlite_pending_operations" in state
    assert "Movie" in state["first_seen"]
    assert "Movie" not in state["queued"]
    assert (root / stage / "Movie" / "fixture.txt").read_text() == "unrelated"
    destination_parent = root / ("original_holding" if stage == "holding" else "holding")
    assert (destination_parent / "Movie" / "fixture.txt").read_text() == "disposable media"


@pytest.mark.skipif(sys.platform != "linux", reason="Atomic no-replace rename requires Linux")
def test_source_entry_substitution_never_clears_intent(tmp_path, monkeypatch):
    import app.sqlite_disposable_lifecycle_flow as flow
    root, database = lab(tmp_path)
    actual = flow.rename_directory_noreplace_at
    def racing_rename(*args):
        source = root / "transient" / "Movie"
        source.rename(root / "transient" / "OriginalMovie")
        source.mkdir()
        (source / "fixture.txt").write_text("replacement")
        actual(*args)
    monkeypatch.setattr(flow, "rename_directory_noreplace_at", racing_rename)
    with pytest.raises(RuntimeError, match="Witness does not match destination"):
        run(root, database)
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert "sqlite_pending_operations" in state
    assert "Movie" in state["first_seen"]
    assert "Movie" not in state["queued"]
    assert (root / "transient" / "OriginalMovie" / "fixture.txt").read_text() == "disposable media"
