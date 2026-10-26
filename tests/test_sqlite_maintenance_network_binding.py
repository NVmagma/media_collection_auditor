"""A new network cannot inherit retained NFS fixture observations."""
import sqlite3

import pytest

from app import sqlite_disposable_maintenance_journal as journal
from app import sqlite_disposable_maintenance_controller as controller
from scripts import sqlite_maintenance_scope_lab as lab


@pytest.fixture
def scope(monkeypatch):
    current = ["net:[1001]"]
    monkeypatch.setattr(journal, "_linux_boot_id", lambda: "17998968-809c-42c5-817a-d7e652aa7b03")
    monkeypatch.setattr(journal, "_linux_network_namespace", lambda: current[0])
    return current


@pytest.mark.parametrize("phase", ["prepared", *journal.NEXT.values()])
def test_network_change_blocks_advance_release_and_receipts(tmp_path, scope, phase):
    root = tmp_path / "lab"
    journal.create_disposable_journal(root, bind_linux_boot=True)
    revision = 0
    while journal.inspect_disposable_journal(root)["phase"] != phase:
        current = journal.inspect_disposable_journal(root)["phase"]
        journal.advance_disposable_journal(root, expected_revision=revision, phase=journal.NEXT[current])
        revision += 1
    before = (root / "maintenance.db").read_bytes()
    scope[0] = "net:[2002]"
    for action in (
        lambda: journal.inspect_disposable_journal(root),
        lambda: journal.advance_disposable_journal(root, expected_revision=revision,
                                                   phase=journal.NEXT.get(phase, "fence_requested")),
        lambda: controller.fence_disposable_fixture(root, expected_revision=revision),
        lambda: controller.release_disposable_fixture(root, expected_revision=revision),
    ):
        with pytest.raises(journal.MaintenanceNetworkScopeChanged):
            action()
    assert (root / "maintenance.db").read_bytes() == before
    assert not list(root.glob("*.fixture-receipt"))


def test_network_drift_after_action_does_not_record_outcome(tmp_path, scope, monkeypatch):
    root = tmp_path / "lab"
    journal.create_disposable_journal(root, bind_linux_boot=True)
    original = controller._receipt
    def drift(root, action):
        receipt = original(root, action)
        scope[0] = "net:[2002]"
        return receipt
    monkeypatch.setattr(controller, "_receipt", drift)
    with pytest.raises(journal.MaintenanceNetworkScopeChanged):
        controller.fence_disposable_fixture(root, expected_revision=0)
    with sqlite3.connect(root / "maintenance.db") as db:
        assert db.execute("SELECT phase FROM events ORDER BY revision").fetchall() == [
            ("prepared",), ("fence_requested",)]
    assert (root / "fence.fixture-receipt").exists()


def test_live_checker_requires_network_mismatch_and_leaves_database_unchanged(tmp_path, scope):
    root = tmp_path / "maintenance-journal"
    journal.create_disposable_journal(root, bind_linux_boot=True)
    journal.advance_disposable_journal(root, expected_revision=0, phase="fence_requested")
    before = (root / "maintenance.db").read_bytes()
    # Same-namespace acceptance must not be misreported as a successful rejection.
    with pytest.raises(RuntimeError, match="unexpectedly accepted"):
        lab.reject_other_network(tmp_path)
    scope[0] = "net:[2002]"
    report = lab.reject_other_network(tmp_path)
    assert report["status"] == "different_network_namespace_rejected"
    assert report["automatic_action"] == "none"
    assert report["production_authorized"] is False
    assert report["writer_exclusion_verified"] is False
    assert (root / "maintenance.db").read_bytes() == before


def test_other_failures_cannot_count_as_network_rejection(tmp_path, scope, monkeypatch):
    root = tmp_path / "maintenance-journal"
    journal.create_disposable_journal(root, bind_linux_boot=True)
    scope[0] = "net:[2002]"
    monkeypatch.setattr(journal, "_linux_boot_id", lambda: "e7ab85f6-24cb-4583-b886-c18109fe6ac9")
    with pytest.raises(RuntimeError, match="boot binding changed"):
        lab.reject_other_network(tmp_path)


def test_fixture_preparation_keeps_namespace_alive_without_release(tmp_path, scope, monkeypatch):
    waits = []
    monkeypatch.setattr(lab.time, "sleep", waits.append)
    lab.prepare(tmp_path)
    assert waits == [60]
    assert (tmp_path / "writer.ready").exists()
    assert journal.inspect_disposable_journal(tmp_path / "maintenance-journal")["phase"] == "fence_requested"
    assert not list((tmp_path / "maintenance-journal").glob("*.fixture-receipt"))


@pytest.mark.parametrize("value", ["net:[0]", "net:[-1]", "mnt:[12]", "net:[12]\n", "net:[1]extra", "x" * 1000])
def test_kernel_network_identity_is_strict(monkeypatch, value):
    monkeypatch.setattr(journal.sys, "platform", "linux")
    monkeypatch.setattr(journal.os, "readlink", lambda path: value)
    with pytest.raises(RuntimeError, match="namespace unavailable"):
        journal._linux_network_namespace()


def test_valid_kernel_network_identity(monkeypatch):
    monkeypatch.setattr(journal.sys, "platform", "linux")
    monkeypatch.setattr(journal.os, "readlink", lambda path: "net:[4026531992]")
    assert journal._linux_network_namespace() == "net:[4026531992]"


def test_missing_kernel_network_identity_does_not_create_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(journal.sys, "platform", "linux")
    monkeypatch.setattr(journal, "_linux_boot_id", lambda: "17998968-809c-42c5-817a-d7e652aa7b03")
    def unavailable(path):
        raise FileNotFoundError("missing namespace")
    monkeypatch.setattr(journal.os, "readlink", unavailable)
    with pytest.raises(RuntimeError, match="namespace unavailable"):
        journal.create_disposable_journal(tmp_path / "lab", bind_linux_boot=True)
    assert not (tmp_path / "lab").exists()
