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


@pytest.mark.parametrize("name", ["state.db", ".sqlite_disposable_rehearsal", ".sqlite_runner.lock"])
def test_replaced_binding_detected_while_lock_held(tmp_path, name):
    root, _ = lab(tmp_path)
    with pytest.raises(RuntimeError, match="binding changed"):
        with module.isolated_runner_lock(root) as verify:
            replacement = root / "replacement"
            replacement.write_bytes((root / name).read_bytes())
            os.replace(replacement, root / name)
            verify()


def test_marker_content_change_detected_without_inode_change(tmp_path):
    root, _ = lab(tmp_path)
    with pytest.raises(RuntimeError, match="marker contents changed"):
        with module.isolated_runner_lock(root) as verify:
            (root / ".sqlite_disposable_rehearsal").write_text("NOT A LAB\n")
            verify()


def test_database_replaced_during_load_stops_before_executor(tmp_path, monkeypatch):
    root, database = lab(tmp_path)
    original_load = module.GuardedSQLiteStateStore.load_with_revision
    def replacing_load(self):
        state, revision = original_load(self)
        replacement = root / "replacement.db"
        replacement.write_bytes(database.read_bytes())
        os.replace(replacement, database)
        return state, revision
    monkeypatch.setattr(module.GuardedSQLiteStateStore, "load_with_revision", replacing_load)
    monkeypatch.setattr(module, "execute_disposable_lifecycle_move",
                        lambda **kwargs: pytest.fail("executor must not run"))
    with pytest.raises(RuntimeError, match="binding changed: state.db"):
        run(root, database)
    assert (root / "transient" / "Movie").is_dir()
    assert not (root / "holding" / "Movie").exists()


def test_root_replaced_at_open_is_rejected_before_lock_creation(tmp_path, monkeypatch):
    root, _ = lab(tmp_path)
    original_open = module.os.open
    def replacing_open(path, flags, *args, **kwargs):
        if path == root:
            root.rename(tmp_path / "original_lab")
            root.mkdir()
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(module.os, "open", replacing_open)
    with pytest.raises(RuntimeError, match="root changed while opening"):
        with module.isolated_runner_lock(root):
            pytest.fail("replacement root accepted")
    assert not (root / ".sqlite_runner.lock").exists()
    assert not (tmp_path / "original_lab" / ".sqlite_runner.lock").exists()


def test_hardlinked_database_rejected_before_lock_creation(tmp_path):
    root, database = lab(tmp_path)
    os.link(database, tmp_path / "alias.db")
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="Unsafe disposable marker or database"):
        run(root, database)
    assert database.read_bytes() == before
    assert not (root / ".sqlite_runner.lock").exists()


def test_binding_check_after_intent_blocks_rename_on_lock_replacement(tmp_path, monkeypatch):
    import app.sqlite_disposable_lifecycle_flow as flow
    root, database = lab(tmp_path)
    original_begin = flow.SQLiteOperationCoordinator.begin_move_with_evidence
    def replacing_begin(self, *args, **kwargs):
        original_begin(self, *args, **kwargs)
        new_lock = root / "replacement.lock"
        new_lock.write_text("")
        os.replace(new_lock, root / ".sqlite_runner.lock")
    monkeypatch.setattr(flow.SQLiteOperationCoordinator, "begin_move_with_evidence", replacing_begin)
    monkeypatch.setattr(flow, "rename_directory_noreplace_at",
                        lambda *args: pytest.fail("rename must not run"))
    with pytest.raises(RuntimeError, match="binding changed: .sqlite_runner.lock"):
        run(root, database)
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert "sqlite_pending_operations" in state
    assert "Movie" in state["first_seen"]
    assert "Movie" not in state["queued"]
    assert (root / "transient" / "Movie").is_dir()


@pytest.mark.parametrize("folder", ["", " ", ".", "..", "../Movie", "/Movie", "a/b", "a\\b", "a\x00b", "a\nb"])
def test_unsafe_title_name_never_creates_lock_or_intent(tmp_path, folder):
    root, database = lab(tmp_path)
    before = database.read_bytes()
    with pytest.raises(ValueError, match="Single safe title folder"):
        run(root, database, title_folder=folder)
    assert database.read_bytes() == before
    assert not (root / ".sqlite_runner.lock").exists()


def test_folder_key_mismatch_stops_before_lock_or_executor(tmp_path, monkeypatch):
    root, database = lab(tmp_path)
    before = database.read_bytes()
    monkeypatch.setattr(module, "execute_disposable_lifecycle_move",
                        lambda **kwargs: pytest.fail("executor must not run"))
    with pytest.raises(RuntimeError, match="folder and tracking key mismatch"):
        run(root, database, title_folder="Other")
    assert database.read_bytes() == before
    assert not (root / ".sqlite_runner.lock").exists()


def named_lab(tmp_path, folder, key):
    root, database = lab(tmp_path)
    (root / "transient" / "Movie").rename(root / "transient" / folder)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state["first_seen"][key] = state["first_seen"].pop("Movie")
    store.save_if_revision(state, revision)
    return root, database


def test_named_title_duplicates_are_blocked_before_intent(tmp_path):
    folder = "Movie A (2025)"
    root, database = named_lab(tmp_path, folder, folder)
    (root / "keep" / folder).mkdir()
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="Ambiguous title locations"):
        module.run_isolated_lifecycle_move(
            root=root, database=database, operation_id="named", media_key=folder,
            title_folder=folder, observed_at=datetime(2026, 1, 1))
    assert database.read_bytes() == before
    assert (root / "transient" / folder).is_dir()
    assert (root / "keep" / folder).is_dir()


@pytest.mark.skipif(sys.platform != "linux", reason="Atomic no-replace rename requires Linux")
@pytest.mark.parametrize("folder,key", [("Movie A (2025)", "Movie A (2025)"),
                                        ("Série A", "TV/Série A")])
def test_named_movie_or_show_moves_only_its_bound_folder(tmp_path, folder, key):
    root, database = named_lab(tmp_path, folder, key)
    unrelated = root / "transient" / "Unrelated"
    unrelated.mkdir()
    (unrelated / "payload").write_text("preserve")
    result = module.run_isolated_lifecycle_move(
        root=root, database=database, operation_id="named", media_key=key,
        title_folder=folder, observed_at=datetime(2026, 1, 1))
    assert result["status"] == "disposable_reconciled"
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert key not in state["first_seen"]
    assert state["queued"][key] == "2026-01-01T00:00:00"
    assert "sqlite_pending_operations" not in state
    assert (root / "holding" / folder / "fixture.txt").read_text() == "disposable media"
    assert (unrelated / "payload").read_text() == "preserve"


@pytest.mark.skipif(sys.platform != "linux", reason="Atomic no-replace rename requires Linux")
def test_named_move_crash_retains_bound_paths_and_clock(tmp_path):
    folder, key = "Show A", "TV/Show A"
    root, database = named_lab(tmp_path, folder, key)
    with pytest.raises(RuntimeError, match="Injected crash after rename"):
        module.run_isolated_lifecycle_move(
            root=root, database=database, operation_id="named", media_key=key,
            title_folder=folder, observed_at=datetime(2026, 1, 1), fault_at="after_rename")
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    details = state["sqlite_pending_operations"]["details"]
    assert details["source"] == str(root / "transient" / folder)
    assert details["destination"] == str(root / "holding" / folder)
    assert details["media_key"] == key
    assert key in state["first_seen"]
    assert key not in state["queued"]
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="Unresolved"):
        module.run_isolated_lifecycle_move(
            root=root, database=database, operation_id="again", media_key=key,
            title_folder=folder, observed_at=datetime(2026, 1, 1))
    assert database.read_bytes() == before


def test_existing_arr_queue_blocks_move_before_new_intent(tmp_path):
    root, database = lab(tmp_path)
    store = GuardedSQLiteStateStore(database)
    state, revision = store.load_with_revision()
    state["arr_sync_pending"]["Movie"] = {"stage": "keep", "root": "/old", "monitored": True}
    store.save_if_revision(state, revision)
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="Existing Arr queue entry"):
        run(root, database, arr_sync_request={
            "service": "radarr", "title_id": 42, "root": "/arr/holding", "monitored": False})
    assert database.read_bytes() == before
    assert (root / "transient" / "Movie").is_dir()
    assert not (root / "holding" / "Movie").exists()


def test_unavailable_mount_binding_stops_before_intent(tmp_path, monkeypatch):
    import app.sqlite_disposable_lifecycle_flow as flow
    root, database = lab(tmp_path)
    before = database.read_bytes()
    monkeypatch.setattr(flow.sys, "platform", "linux")
    def unavailable(*args):
        raise RuntimeError("Rename mount binding unavailable")
    monkeypatch.setattr(flow, "capture_rename_mount_binding", unavailable)
    with pytest.raises(RuntimeError, match="mount binding unavailable"):
        run(root, database)
    assert database.read_bytes() == before
    assert (root / "transient" / "Movie").is_dir()


def test_changed_mount_after_intent_blocks_rename_and_retains_intent(tmp_path, monkeypatch):
    import app.sqlite_disposable_lifecycle_flow as flow
    root, database = lab(tmp_path)
    monkeypatch.setattr(flow.sys, "platform", "linux")
    monkeypatch.setattr(flow, "capture_rename_mount_binding", lambda *args: {"fixture": "mount"})
    def changed_after_intent(*args):
        state, _ = GuardedSQLiteStateStore(database).load_with_revision()
        if "sqlite_pending_operations" in state:
            raise RuntimeError("Rename mount binding changed")
    monkeypatch.setattr(flow, "assert_rename_mount_binding", changed_after_intent)
    monkeypatch.setattr(flow, "rename_directory_noreplace_at",
                        lambda *args: pytest.fail("rename must not run"))
    with pytest.raises(RuntimeError, match="mount binding changed"):
        run(root, database)
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert "sqlite_pending_operations" in state
    assert "Movie" in state["first_seen"]
    assert (root / "transient" / "Movie").is_dir()


def test_unsupported_rename_still_retains_intent_without_filesystem_blacklist(tmp_path, monkeypatch):
    import app.sqlite_disposable_lifecycle_flow as flow
    import app.sqlite_rename_mount_binding as mounts
    root, database = lab(tmp_path)
    before = database.read_bytes()
    monkeypatch.setattr(flow.sys, "platform", "linux")
    monkeypatch.setattr(mounts, "read_mount_namespace_identity", lambda: (1, 2))
    monkeypatch.setattr(mounts, "read_fd_mount_id", lambda fd: 10)
    monkeypatch.setattr(mounts, "read_mount_filesystem", lambda mount_id: "fuse.shfs")
    def unsupported(*args):
        raise RuntimeError("Atomic no-replace rename unsupported")
    monkeypatch.setattr(flow, "rename_directory_noreplace_at", unsupported)
    with pytest.raises(RuntimeError, match="no-replace rename unsupported"):
        run(root, database)
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert "sqlite_pending_operations" in state
    assert "Movie" in state["first_seen"]
    assert (root / "transient" / "Movie").is_dir()
    assert not (root / "holding" / "Movie").exists()
