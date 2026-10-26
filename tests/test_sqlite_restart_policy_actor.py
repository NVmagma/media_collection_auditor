import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("restart_actor", Path(__file__).parents[1] / "scripts/sqlite_restart_policy_actor.py")
actor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(actor)


def test_restart_does_not_replay_previous_process_crash(tmp_path):
    (tmp_path / ".fixture-only").write_bytes(actor.MARKER)
    (tmp_path / "starts").write_text("0")
    assert actor.start(tmp_path) == 1
    (tmp_path / "crash.1").touch()
    assert actor.crash_requested(tmp_path, 1)
    assert actor.start(tmp_path) == 2
    assert not actor.crash_requested(tmp_path, 2)
    (tmp_path / "crash.2").touch()
    assert actor.crash_requested(tmp_path, 2)
    assert actor.start(tmp_path) == 3
    with pytest.raises(RuntimeError, match="bound"):
        actor.start(tmp_path)
    assert (tmp_path / "starts").read_text() == "3"


def test_marker_required_before_any_write(tmp_path):
    (tmp_path / ".fixture-only").write_bytes(b"wrong")
    (tmp_path / "starts").write_text("0")
    with pytest.raises(RuntimeError, match="disposable"):
        actor.start(tmp_path)
    assert (tmp_path / "starts").read_text() == "0"
