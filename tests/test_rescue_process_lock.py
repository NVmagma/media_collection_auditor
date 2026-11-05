"""Real process contention around disposable manual rescue; no service calls."""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))
import manual_rescue
from state_lock import state_writer_lock


@pytest.fixture
def rescue(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITOR_STATE_BACKEND", "json")
    source = tmp_path / "removal" / "Example"
    source.mkdir(parents=True)
    (source / "payload").write_text("disposable")
    for stage in ("keep", "holding"):
        (tmp_path / stage).mkdir()
    state_file = tmp_path / "state.json"
    state = {name: {} for name in ("first_seen", "queued", "in_removal", "keep_seen", "arr_sync_pending")}
    state["in_removal"]["Example"] = "2024-01-01T00:00:00"
    state["unknown_history"] = {"preserve": True}
    state_file.write_text(json.dumps(state))
    library = {"name": "Movies", **{stage: str(tmp_path / stage) for stage in ("removal", "holding", "keep")},
               "app_keep": "/fixture/keep", "app_holding": "/fixture/hold"}
    library["arr"] = SimpleNamespace(notify_moved=Mock(return_value=True))
    def move(source, destination):
        shutil.move(source, destination)
        return None
    auditor = SimpleNamespace(STATE_FILE=str(state_file), DRY_RUN=False,
        build_libraries=Mock(return_value=[library]),
        is_within=lambda path, base: os.path.commonpath((path, base)) == base,
        state_key=lambda lib, title: title, load_state=Mock(side_effect=lambda: json.loads(state_file.read_text())),
        safe_move_directory=Mock(side_effect=move), record_action=Mock())
    monkeypatch.setattr(manual_rescue, "importlib", SimpleNamespace(import_module=lambda name: auditor))
    monkeypatch.setattr(manual_rescue, "begin_rescue", Mock(return_value=True))
    monkeypatch.setattr(manual_rescue, "end_rescue", Mock())
    monkeypatch.setattr(manual_rescue, "new_record", lambda *args: {"started_at": "fixture"})
    monkeypatch.setattr(manual_rescue, "finish_record", lambda *args: None)
    return tmp_path, state_file, source, auditor, library


@pytest.mark.parametrize("lock", ["migration_lock", "audit_run_lock", "state_writer_lock"])
def test_another_process_blocks_rescue_before_load_or_move(rescue, lock):
    root, state_file, source, auditor, library = rescue
    before = state_file.read_bytes()
    script = '''
import sys
sys.path.insert(0, sys.argv[1])
import state_lock
with getattr(state_lock, sys.argv[3])(sys.argv[2]):
    print("LOCKED", flush=True)
    sys.stdin.readline()
'''
    child = subprocess.Popen([sys.executable, "-B", "-c", script, str(APP), str(state_file), lock],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([child.stdout], [], [], 10)[0], "Lock child did not become ready"
        assert child.stdout.readline().strip() == "LOCKED"
        result = manual_rescue.rescue_title("Movies", "Example", "keep")
        assert result[0] is False and result[2] == 409
        auditor.build_libraries.assert_not_called()
        auditor.load_state.assert_not_called()
        auditor.safe_move_directory.assert_not_called()
        library["arr"].notify_moved.assert_not_called()
        assert source.is_dir() and state_file.read_bytes() == before
        manual_rescue.end_rescue.assert_called_once()
    finally:
        child.communicate("\n", timeout=10)
    assert child.returncode == 0
    with state_writer_lock(state_file):
        pass


@pytest.mark.parametrize("backend", ["unsupported", "unknown", ""])
def test_unsupported_backend_stops_before_claim_import_or_lock(rescue, monkeypatch, backend):
    root, state_file, source, auditor, library = rescue
    monkeypatch.setenv("AUDITOR_STATE_BACKEND", backend)
    result = manual_rescue.rescue_title("Movies", "Example", "keep")
    assert result[0] is False and result[2] == 409
    manual_rescue.begin_rescue.assert_not_called()
    manual_rescue.end_rescue.assert_not_called()
    auditor.build_libraries.assert_not_called()
    assert not Path(str(state_file) + ".migration.lock").exists()
    assert source.is_dir()


def blocked_from_process(state_file):
    script = '''
import sys
sys.path.insert(0, sys.argv[1])
from state_lock import migration_lock, StateLockBusy
try:
    with migration_lock(sys.argv[2]):
        print("OWNED")
except StateLockBusy:
    print("BLOCKED")
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, str(APP), str(state_file)],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "BLOCKED"


@pytest.mark.parametrize("destination", ["keep", "holding"])
def test_lock_covers_load_move_checkpoint_and_notification(rescue, monkeypatch, destination):
    root, state_file, source, auditor, library = rescue
    original_load = auditor.load_state.side_effect
    def load():
        blocked_from_process(state_file)
        return original_load()
    auditor.load_state.side_effect = load
    original_move = auditor.safe_move_directory.side_effect
    def move(*args):
        blocked_from_process(state_file)
        return original_move(*args)
    auditor.safe_move_directory.side_effect = move
    def notify(*args):
        blocked_from_process(state_file)
        state = json.loads(state_file.read_text())
        assert "Example" not in state["in_removal"]
        assert "Example" in state["keep_seen" if destination == "keep" else "queued"]
        return True
    library["arr"].notify_moved.side_effect = notify
    result = manual_rescue.rescue_title("Movies", "Example", destination)
    assert result[0] is True and result[2] == 200
    assert not source.exists() and (root / destination / "Example" / "payload").read_text() == "disposable"
    assert json.loads(state_file.read_text())["unknown_history"] == {"preserve": True}
    manual_rescue.end_rescue.assert_called_once()
    with state_writer_lock(state_file):
        pass


def test_replaced_lock_blocks_before_media_move(rescue):
    root, state_file, source, auditor, library = rescue
    before = state_file.read_bytes()
    original_load = auditor.load_state.side_effect
    def replaced():
        state = original_load()
        path = Path(str(state_file) + ".migration.lock")
        path.rename(root / "retained-original-lock")
        path.write_text("")
        return state
    auditor.load_state.side_effect = replaced
    result = manual_rescue.rescue_title("Movies", "Example", "keep")
    assert result[0] is False and result[2] == 500
    auditor.safe_move_directory.assert_not_called()
    library["arr"].notify_moved.assert_not_called()
    assert source.is_dir() and state_file.read_bytes() == before


def test_move_error_releases_both_guards_without_updating_state(rescue):
    root, state_file, source, auditor, library = rescue
    before = state_file.read_bytes()
    auditor.safe_move_directory.side_effect = None
    auditor.safe_move_directory.return_value = "injected refusal"
    result = manual_rescue.rescue_title("Movies", "Example", "keep")
    assert result[0] is False and result[2] == 409
    assert source.is_dir() and state_file.read_bytes() == before
    library["arr"].notify_moved.assert_not_called()
    manual_rescue.end_rescue.assert_called_once()
    with state_writer_lock(state_file):
        pass




def test_save_error_preserves_bytes_and_releases_coordination(rescue, monkeypatch):
    root, state_file, source, auditor, library = rescue
    before = state_file.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("injected state-save failure")
    monkeypatch.setattr(manual_rescue.json, "dump", fail)
    result = manual_rescue.rescue_title("Movies", "Example", "keep")
    assert result[0] is False and result[2] == 500
    assert state_file.read_bytes() == before
    assert (root / "keep" / "Example" / "payload").read_text() == "disposable"
    library["arr"].notify_moved.assert_not_called()
    manual_rescue.end_rescue.assert_called_once()
    with state_writer_lock(state_file):
        pass


def test_arr_failure_leaves_saved_rescue_and_releases_coordination(rescue):
    root, state_file, source, auditor, library = rescue
    library["arr"].notify_moved.return_value = False
    result = manual_rescue.rescue_title("Movies", "Example", "keep")
    assert result[0] is True and result[2] == 200 and "sync failed" in result[1]
    assert "Example" in json.loads(state_file.read_text())["keep_seen"]
    assert (root / "keep" / "Example" / "payload").read_text() == "disposable"
    manual_rescue.end_rescue.assert_called_once()
    with state_writer_lock(state_file):
        pass


@pytest.mark.parametrize("setting", ["STATE_FILE", "DRY_RUN"])
def test_configuration_drift_cannot_change_lock_target_or_dry_run_during_rescue(rescue, setting):
    root, state_file, source, auditor, library = rescue
    before = state_file.read_bytes()
    original_load = auditor.load_state.side_effect
    def changed():
        state = original_load()
        setattr(auditor, setting, str(root / "other-state.json") if setting == "STATE_FILE" else True)
        return state
    auditor.load_state.side_effect = changed
    result = manual_rescue.rescue_title("Movies", "Example", "keep")
    assert result[0] is False and result[2] == 500
    auditor.safe_move_directory.assert_not_called()
    library["arr"].notify_moved.assert_not_called()
    assert source.is_dir() and state_file.read_bytes() == before
    assert not (root / "other-state.json").exists()
    assert not (root / "other-state.json.rescue.tmp").exists()
