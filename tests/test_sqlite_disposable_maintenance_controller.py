import os
from pathlib import Path
import subprocess
import sys

import pytest

from app import sqlite_disposable_maintenance_controller as controller
from app.sqlite_disposable_maintenance_journal import (
    advance_disposable_journal as advance, create_disposable_journal as create,
    inspect_disposable_journal as inspect,
)


def prepare(tmp_path, release=False):
    root = tmp_path / "lab"
    create(root)
    if release:
        controller.fence_disposable_fixture(root, expected_revision=0)
        advance(root, expected_revision=2, phase="work_pending")
        advance(root, expected_revision=3, phase="outcomes_verified")
    return root


def test_ordered_controller_retains_receipts_and_never_authorizes(tmp_path):
    root = prepare(tmp_path, release=True)
    report = controller.release_disposable_fixture(root, expected_revision=4)
    assert report["phase"] == "released"
    assert report["production_authorized"] is False
    assert report["external_writer_exclusion_verified"] is False
    assert (root / "fence.fixture-receipt").is_file()
    assert (root / "release.fixture-receipt").is_file()


def test_release_before_verified_outcomes_has_no_action(tmp_path):
    root = prepare(tmp_path)
    controller.fence_disposable_fixture(root, expected_revision=0)
    with pytest.raises(RuntimeError):
        controller.release_disposable_fixture(root, expected_revision=2)
    assert inspect(root)["phase"] == "fixture_fenced"
    assert not (root / "release.fixture-receipt").exists()


@pytest.mark.parametrize("release", [False, True])
def test_action_failure_retains_durable_request_and_blocks_retry(tmp_path, monkeypatch, release):
    root = prepare(tmp_path, release)
    action = controller.release_disposable_fixture if release else controller.fence_disposable_fixture
    revision = 4 if release else 0
    def fail(root, name):
        assert inspect(root)["phase"] == name + "_requested"
        raise OSError("simulated uncertain external outcome")
    monkeypatch.setattr(controller, "_receipt", fail)
    with pytest.raises(OSError):
        action(root, expected_revision=revision)
    assert inspect(root)["phase"] == ("release_requested" if release else "fence_requested")
    with pytest.raises(RuntimeError):
        action(root, expected_revision=revision + 1)


@pytest.mark.parametrize("release", [False, True])
def test_death_after_receipt_before_outcome_never_replays(tmp_path, release):
    root = prepare(tmp_path, release)
    code = '''
import os, sys
from app import sqlite_disposable_maintenance_controller as c
original = c._receipt
def crash(root, action):
    original(root, action)
    os._exit(23)
c._receipt = crash
action = c.release_disposable_fixture if sys.argv[2] == 'release' else c.fence_disposable_fixture
action(sys.argv[1], expected_revision=int(sys.argv[3]))
'''
    name, revision = ("release", 4) if release else ("fence", 0)
    result = subprocess.run([sys.executable, "-B", "-c", code, str(root), name, str(revision)],
                            cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=15)
    assert result.returncode == 23
    receipt = root / (name + ".fixture-receipt")
    before = receipt.read_bytes()
    assert inspect(root)["phase"] == name + "_requested"
    assert inspect(root)["automatic_action"] == "none"
    action = controller.release_disposable_fixture if release else controller.fence_disposable_fixture
    with pytest.raises(RuntimeError):
        action(root, expected_revision=revision + 1)
    assert receipt.read_bytes() == before


def test_controller_lock_spans_action(tmp_path, monkeypatch):
    from app.sqlite_lock import StateLockBusy
    root = prepare(tmp_path)
    original = controller._receipt
    def compete(root, action):
        with pytest.raises(StateLockBusy):
            advance(root, expected_revision=1, phase="fixture_fenced")
        original(root, action)
    monkeypatch.setattr(controller, "_receipt", compete)
    assert controller.fence_disposable_fixture(root, expected_revision=0)["phase"] == "fixture_fenced"


def test_existing_receipt_is_never_overwritten(tmp_path):
    root = prepare(tmp_path)
    receipt = root / "fence.fixture-receipt"
    receipt.write_bytes(b"previous uncertain action")
    with pytest.raises(FileExistsError):
        controller.fence_disposable_fixture(root, expected_revision=0)
    assert receipt.read_bytes() == b"previous uncertain action"
    assert inspect(root)["phase"] == "fence_requested"


def test_lost_lock_after_action_retains_request(tmp_path, monkeypatch):
    root = prepare(tmp_path)
    original = controller._receipt
    def replace_lock(root, action):
        original(root, action)
        (root / "controller.lock").rename(root / "old-controller.lock")
        (root / "controller.lock").touch()
    monkeypatch.setattr(controller, "_receipt", replace_lock)
    with pytest.raises(RuntimeError, match="binding changed"):
        controller.fence_disposable_fixture(root, expected_revision=0)
    assert inspect(root)["phase"] == "fence_requested"
    assert (root / "fence.fixture-receipt").exists()
