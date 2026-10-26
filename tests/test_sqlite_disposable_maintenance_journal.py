import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.sqlite_disposable_maintenance_journal import (
    NEXT, advance_disposable_journal as advance,
    create_disposable_journal as create, inspect_disposable_journal as inspect,
)


def test_ordered_fixture_never_authorizes_production(tmp_path):
    root = tmp_path / "lab"
    report = create(root)
    for revision, phase in enumerate(NEXT.values()):
        report = advance(root, expected_revision=revision, phase=phase)
        assert report == inspect(root)
        assert report["production_authorized"] is False
        assert report["external_writer_exclusion_verified"] is False
        assert report["automatic_action"] == "none"
    assert report["status"] == "fixture_complete"
    with pytest.raises(RuntimeError):
        advance(root, expected_revision=6, phase="fence_requested")


@pytest.mark.parametrize("phase", ["fixture_fenced", "work_pending", "release_requested", "released", None])
def test_cannot_skip_checkpoints(tmp_path, phase):
    root = tmp_path / "lab"
    before = create(root)
    with pytest.raises(RuntimeError):
        advance(root, expected_revision=0, phase=phase)
    assert inspect(root) == before


def test_stale_controller_cannot_release_or_replay(tmp_path):
    root = tmp_path / "lab"
    create(root)
    before = advance(root, expected_revision=0, phase="fence_requested")
    with pytest.raises(RuntimeError, match="Stale"):
        advance(root, expected_revision=0, phase="fixture_fenced")
    assert inspect(root) == before


@pytest.mark.parametrize("revision", [True, -1, 1.0, "0"])
def test_revision_is_strict(tmp_path, revision):
    root = tmp_path / "lab"
    create(root)
    with pytest.raises(ValueError):
        advance(root, expected_revision=revision, phase="fence_requested")


@pytest.mark.parametrize("checkpoint", list(NEXT.values())[:-1])
def test_process_death_preserves_pending_checkpoint(tmp_path, checkpoint):
    root = tmp_path / "lab"
    create(root)
    code = '''
import os, sys
from app.sqlite_disposable_maintenance_journal import NEXT, advance_disposable_journal
for revision, phase in enumerate(NEXT.values()):
    advance_disposable_journal(sys.argv[1], expected_revision=revision, phase=phase)
    if phase == sys.argv[2]:
        os._exit(17)
'''
    result = subprocess.run([sys.executable, "-B", "-c", code, str(root), checkpoint],
                            cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=15)
    assert result.returncode == 17
    before = (root / "maintenance.db").read_bytes()
    report = inspect(root)
    assert report["phase"] == checkpoint
    assert report["status"] == "review_required"
    assert report["automatic_action"] == "none"
    assert (root / "maintenance.db").read_bytes() == before


def test_unknown_commit_rolls_back_without_clearing_intent(tmp_path):
    root = tmp_path / "lab"
    create(root)
    advance(root, expected_revision=0, phase="fence_requested")
    code = '''
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute("BEGIN IMMEDIATE")
db.execute("INSERT INTO events VALUES (2, 'fixture_fenced')")
os._exit(18)
'''
    result = subprocess.run([sys.executable, "-B", "-c", code, str(root / "maintenance.db")], timeout=15)
    assert result.returncode == 18
    assert inspect(root)["phase"] == "fence_requested"


def test_existing_root_missing_database_and_aliases_rejected(tmp_path):
    root = tmp_path / "lab"
    create(root)
    with pytest.raises(FileExistsError):
        create(root)
    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        inspect(missing)
    assert not missing.exists()
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError):
        advance(alias, expected_revision=0, phase="fence_requested")


def test_tampered_history_blocks_inspection_and_advance(tmp_path):
    root = tmp_path / "lab"
    create(root)
    with sqlite3.connect(root / "maintenance.db") as db:
        db.execute("INSERT INTO events VALUES (1, 'released')")
    for action in (lambda: inspect(root), lambda: advance(root, expected_revision=1, phase="fence_requested")):
        with pytest.raises(RuntimeError, match="history"):
            action()


def test_competing_process_cannot_advance_held_controller(tmp_path):
    from app.sqlite_lock import _exclusive_lock
    root = tmp_path / "lab"
    before = create(root)
    code = '''
import sys
from app.sqlite_disposable_maintenance_journal import advance_disposable_journal
from app.sqlite_lock import StateLockBusy
try:
    advance_disposable_journal(sys.argv[1], expected_revision=0, phase="fence_requested")
except StateLockBusy:
    sys.exit(19)
'''
    with _exclusive_lock(root / "controller.lock", "busy"):
        result = subprocess.run([sys.executable, "-B", "-c", code, str(root)],
                                cwd=Path(__file__).resolve().parents[1], timeout=15)
        assert result.returncode == 19
        assert inspect(root) == before


def test_missing_fixture_marker_rejected_without_creating_lock(tmp_path):
    root = tmp_path / "lab"
    create(root)
    (root / ".disposable_maintenance").unlink()
    with pytest.raises(FileNotFoundError):
        advance(root, expected_revision=0, phase="fence_requested")
    assert not (root / "controller.lock").exists()
