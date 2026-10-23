"""Boot drift never becomes permission to continue or release a fixture."""
import io
import sqlite3

import pytest

from app import sqlite_disposable_maintenance_journal as journal
from app import sqlite_disposable_maintenance_controller as controller

BOOT_A = "17998968-809c-42c5-817a-d7e652aa7b03"
BOOT_B = "e7ab85f6-24cb-4583-b886-c18109fe6ac9"


@pytest.fixture(autouse=True)
def private_network_fixture(monkeypatch):
    # Deterministic scope for portable decision tests; live Docker checks use
    # actual kernel namespace identities without this test replacement.
    monkeypatch.setattr(journal, "_linux_network_namespace", lambda: "net:[1001]")


@pytest.mark.parametrize("phase", ["prepared", *journal.NEXT.values()])
def test_different_boot_retains_every_checkpoint_without_recovery(tmp_path, monkeypatch, phase):
    monkeypatch.setattr(journal, "_linux_boot_id", lambda: BOOT_A)
    root = tmp_path / "lab"
    journal.create_disposable_journal(root, bind_linux_boot=True)
    revision = 0
    while journal.inspect_disposable_journal(root)["phase"] != phase:
        current = journal.inspect_disposable_journal(root)["phase"]
        journal.advance_disposable_journal(root, expected_revision=revision, phase=journal.NEXT[current])
        revision += 1
    before = (root / "maintenance.db").read_bytes()
    monkeypatch.setattr(journal, "_linux_boot_id", lambda: BOOT_B)
    for action in (
        lambda: journal.inspect_disposable_journal(root),
        lambda: journal.advance_disposable_journal(root, expected_revision=revision,
                                                   phase=journal.NEXT.get(phase, "fence_requested")),
        lambda: controller.fence_disposable_fixture(root, expected_revision=revision),
        lambda: controller.release_disposable_fixture(root, expected_revision=revision),
    ):
        with pytest.raises(journal.MaintenanceBootScopeChanged, match="boot binding changed"):
            action()
    assert (root / "maintenance.db").read_bytes() == before
    assert not list(root.glob("*.fixture-receipt"))


def test_same_boot_new_reader_preserves_pending_intent(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "_linux_boot_id", lambda: BOOT_A)
    root = tmp_path / "lab"
    journal.create_disposable_journal(root, bind_linux_boot=True)
    journal.advance_disposable_journal(root, expected_revision=0, phase="fence_requested")
    before = (root / "maintenance.db").read_bytes()
    report = journal.inspect_disposable_journal(root)
    assert report["phase"] == "fence_requested"
    assert report["automatic_action"] == "none"
    assert report["production_authorized"] is False
    assert (root / "maintenance.db").read_bytes() == before


def test_boot_drift_after_action_retains_intent_without_outcome(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "_linux_boot_id", lambda: BOOT_A)
    root = tmp_path / "lab"
    journal.create_disposable_journal(root, bind_linux_boot=True)
    original = controller._receipt
    def drift(root, action):
        receipt = original(root, action)
        monkeypatch.setattr(journal, "_linux_boot_id", lambda: BOOT_B)
        return receipt
    monkeypatch.setattr(controller, "_receipt", drift)
    with pytest.raises(journal.MaintenanceBootScopeChanged, match="boot binding changed"):
        controller.fence_disposable_fixture(root, expected_revision=0)
    with sqlite3.connect(root / "maintenance.db") as db:
        assert db.execute("SELECT revision, phase FROM events ORDER BY revision").fetchall() == [
            (0, "prepared"), (1, "fence_requested")]
    assert (root / "fence.fixture-receipt").exists()


def test_missing_boot_capability_does_not_create_or_modify_fixture(tmp_path, monkeypatch):
    root = tmp_path / "lab"
    monkeypatch.setattr(journal, "_linux_boot_id", lambda: BOOT_A)
    journal.create_disposable_journal(root, bind_linux_boot=True)
    before = (root / "maintenance.db").read_bytes()
    def unavailable():
        raise RuntimeError("Linux boot identity unavailable")
    monkeypatch.setattr(journal, "_linux_boot_id", unavailable)
    with pytest.raises(RuntimeError, match="identity unavailable"):
        controller.fence_disposable_fixture(root, expected_revision=0)
    assert (root / "maintenance.db").read_bytes() == before
    assert not (root / "fence.fixture-receipt").exists()
    with pytest.raises(RuntimeError, match="identity unavailable"):
        journal.create_disposable_journal(tmp_path / "new", bind_linux_boot=True)
    assert not (tmp_path / "new").exists()


def test_legacy_binding_is_not_automatically_upgraded(tmp_path):
    root = tmp_path / "lab"
    journal.create_disposable_journal(root)
    with sqlite3.connect(root / "maintenance.db") as db:
        db.execute("ALTER TABLE fixture_binding DROP COLUMN linux_boot_id")
    before = (root / "maintenance.db").read_bytes()
    with pytest.raises(RuntimeError, match="boot binding unavailable"):
        controller.fence_disposable_fixture(root, expected_revision=0)
    assert (root / "maintenance.db").read_bytes() == before
    assert not (root / "fence.fixture-receipt").exists()


@pytest.mark.parametrize("raw", [b"", b"unknown\n", BOOT_A.upper().encode() + b"\n",
                                 BOOT_A.encode(), BOOT_A.encode() + b"\nextra",
                                 b"00000000-0000-0000-0000-000000000000\n", b"\xff" * 37])
def test_kernel_identity_requires_bounded_canonical_uuid(monkeypatch, raw):
    monkeypatch.setattr(journal.sys, "platform", "linux")
    monkeypatch.setattr("builtins.open", lambda *args: io.BytesIO(raw))
    with pytest.raises(RuntimeError, match="identity unavailable"):
        journal._linux_boot_id()


def test_valid_kernel_boot_identity(monkeypatch):
    monkeypatch.setattr(journal.sys, "platform", "linux")
    monkeypatch.setattr("builtins.open", lambda *args: io.BytesIO(BOOT_A.encode() + b"\n"))
    assert journal._linux_boot_id() == BOOT_A


def test_unsupported_platform_has_no_identity_fallback(monkeypatch):
    monkeypatch.setattr(journal.sys, "platform", "darwin")
    with pytest.raises(RuntimeError, match="identity unavailable"):
        journal._linux_boot_id()
