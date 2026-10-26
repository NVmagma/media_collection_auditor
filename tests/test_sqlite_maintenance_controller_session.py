"""Matching/recycled kernel identifiers never transfer a Linux fixture session."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app import sqlite_disposable_maintenance_journal as journal
from app import sqlite_disposable_maintenance_controller as controller
from app.sqlite_maintenance_review import review_disposable_maintenance
from scripts.sqlite_maintenance_scope_lab import reject_other_controller

BOOT = "17998968-809c-42c5-817a-d7e652aa7b03"


@pytest.fixture(autouse=True)
def fixed_kernel_scope(monkeypatch):
    monkeypatch.setattr(journal, "_linux_boot_id", lambda: BOOT)
    monkeypatch.setattr(journal, "_linux_network_namespace", lambda: "net:[1001]")


@pytest.mark.parametrize("phase", ["prepared", *journal.NEXT.values()])
def test_new_session_cannot_advance_or_release_even_when_all_identifiers_match(tmp_path, monkeypatch, phase):
    root = tmp_path / "lab"
    journal.create_disposable_journal(root, bind_linux_boot=True)
    revision = 0
    while journal.inspect_disposable_journal(root)["phase"] != phase:
        current = journal.inspect_disposable_journal(root)["phase"]
        journal.advance_disposable_journal(root, expected_revision=revision, phase=journal.NEXT[current])
        revision += 1
    before = (root / "maintenance.db").read_bytes()
    monkeypatch.setattr(journal, "_CONTROLLER_SESSION", "replacement-session".ljust(64, "0"))
    for action in (
        lambda: journal.advance_disposable_journal(root, expected_revision=revision,
                                                   phase=journal.NEXT.get(phase, "fence_requested")),
        lambda: controller.fence_disposable_fixture(root, expected_revision=revision),
        lambda: controller.release_disposable_fixture(root, expected_revision=revision),
    ):
        with pytest.raises(journal.MaintenanceControllerSessionChanged):
            action()
    assert (root / "maintenance.db").read_bytes() == before
    assert not list(root.glob("*.fixture-receipt"))
    report = review_disposable_maintenance(root)
    assert report["scope"] == {"path_identity": "matching", "linux_boot": "matching",
                               "network_namespace": "matching"}
    assert report["scope_comparison"] == "identifiers_only"
    assert report["controller_session_verified"] is False
    assert report["resume_authorized"] is False


@pytest.mark.parametrize("inherit", ["neither", "pid", "token"])
def test_independent_interpreter_cannot_inherit_process_or_kernel_scope(tmp_path, inherit):
    root = tmp_path / "lab"
    journal.create_disposable_journal(root, bind_linux_boot=True)
    journal.advance_disposable_journal(root, expected_revision=0, phase="fence_requested")
    before = (root / "maintenance.db").read_bytes()
    code = '''
import sqlite3, sys
from app import sqlite_disposable_maintenance_journal as journal
journal._linux_boot_id = lambda: "17998968-809c-42c5-817a-d7e652aa7b03"
journal._linux_network_namespace = lambda: "net:[1001]"
with sqlite3.connect(sys.argv[1] + "/maintenance.db") as db:
    pid, token = db.execute("SELECT controller_pid, controller_session FROM fixture_binding").fetchone()
if sys.argv[2] == "pid":
    journal.os.getpid = lambda: pid  # Simulate PID reuse, with a fresh interpreter token.
elif sys.argv[2] == "token":
    journal._CONTROLLER_SESSION = token  # Simulate copied module memory after fork.
try:
    journal.advance_disposable_journal(sys.argv[1], expected_revision=1, phase="fixture_fenced")
except journal.MaintenanceControllerSessionChanged:
    sys.exit(23)
sys.exit(24)
'''
    result = subprocess.run([sys.executable, "-B", "-c", code, str(root), inherit],
                            cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 23, result.stderr
    assert (root / "maintenance.db").read_bytes() == before
    assert journal.inspect_disposable_journal(root)["phase"] == "fence_requested"


def test_original_session_can_complete_only_explicit_synthetic_steps(tmp_path):
    root = tmp_path / "lab"
    journal.create_disposable_journal(root, bind_linux_boot=True)
    assert controller.fence_disposable_fixture(root, expected_revision=0)["phase"] == "fixture_fenced"
    journal.advance_disposable_journal(root, expected_revision=2, phase="work_pending")
    journal.advance_disposable_journal(root, expected_revision=3, phase="outcomes_verified")
    report = controller.release_disposable_fixture(root, expected_revision=4)
    assert report["phase"] == "released"
    assert report["production_authorized"] is False


def test_session_drift_after_action_retains_pending_intent(tmp_path, monkeypatch):
    root = tmp_path / "lab"
    journal.create_disposable_journal(root, bind_linux_boot=True)
    original = controller._receipt
    def drift(root, action):
        result = original(root, action)
        monkeypatch.setattr(journal, "_CONTROLLER_SESSION", "changed".ljust(64, "0"))
        return result
    monkeypatch.setattr(controller, "_receipt", drift)
    with pytest.raises(journal.MaintenanceControllerSessionChanged):
        controller.fence_disposable_fixture(root, expected_revision=0)
    assert journal.inspect_disposable_journal(root)["phase"] == "fence_requested"
    assert (root / "fence.fixture-receipt").exists()


def test_missing_session_record_is_not_automatically_recreated(tmp_path):
    root = tmp_path / "lab"
    journal.create_disposable_journal(root, bind_linux_boot=True)
    with sqlite3.connect(root / "maintenance.db") as db:
        db.execute("ALTER TABLE fixture_binding DROP COLUMN controller_session")
    before = (root / "maintenance.db").read_bytes()
    with pytest.raises(RuntimeError, match="session binding unavailable"):
        controller.fence_disposable_fixture(root, expected_revision=0)
    assert (root / "maintenance.db").read_bytes() == before
    assert not (root / "fence.fixture-receipt").exists()


def test_live_check_accepts_only_specific_session_rejection(tmp_path, monkeypatch):
    root = tmp_path / "maintenance-journal"
    journal.create_disposable_journal(root, bind_linux_boot=True)
    journal.advance_disposable_journal(root, expected_revision=0, phase="fence_requested")
    before = (root / "maintenance.db").read_bytes()
    monkeypatch.setattr(journal, "_CONTROLLER_SESSION", "changed".ljust(64, "0"))
    report = reject_other_controller(tmp_path)
    assert report["status"] == "different_controller_session_rejected"
    assert report["transition_completed"] is False
    assert (root / "maintenance.db").read_bytes() == before
    assert journal._CONTROLLER_SESSION not in json.dumps(review_disposable_maintenance(root))
    monkeypatch.setattr(journal, "_linux_network_namespace", lambda: "net:[2002]")
    with pytest.raises(journal.MaintenanceNetworkScopeChanged):
        reject_other_controller(tmp_path)
