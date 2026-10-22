import shutil
import sqlite3

import pytest

from app import sqlite_disposable_maintenance_controller as controller
from app.sqlite_disposable_maintenance_journal import (
    create_disposable_journal as create, inspect_disposable_journal as inspect,
)


def test_copied_journal_does_not_inherit_scope(tmp_path):
    root, copied = tmp_path / "lab", tmp_path / "copy"
    create(root)
    shutil.copytree(root, copied)
    before = (copied / "maintenance.db").read_bytes()
    with pytest.raises(RuntimeError, match="binding changed"):
        inspect(copied)
    with pytest.raises(RuntimeError, match="binding changed"):
        controller.fence_disposable_fixture(copied, expected_revision=0)
    assert not (copied / "fence.fixture-receipt").exists()
    assert (copied / "maintenance.db").read_bytes() == before
    assert inspect(root)["phase"] == "prepared"


def test_same_path_database_replacement_blocks_action(tmp_path):
    root = tmp_path / "lab"
    create(root)
    database = root / "maintenance.db"
    database.rename(root / "original.db")
    shutil.copyfile(root / "original.db", database)
    with pytest.raises(RuntimeError, match="binding changed"):
        controller.fence_disposable_fixture(root, expected_revision=0)
    assert not (root / "fence.fixture-receipt").exists()


@pytest.mark.parametrize("change", ["root_alias", "database", "marker"])
def test_scope_drift_after_action_never_records_completion(tmp_path, monkeypatch, change):
    root = tmp_path / "lab"
    create(root)
    original = controller._receipt
    retained = tmp_path / "retained"
    def drift(root, action):
        original(root, action)
        if change == "root_alias":
            root.rename(retained)
            root.symlink_to(retained, target_is_directory=True)
        elif change == "database":
            (root / "maintenance.db").rename(root / "original.db")
            shutil.copyfile(root / "original.db", root / "maintenance.db")
        else:
            (root / ".disposable_maintenance").write_bytes(b"invalid marker")
    monkeypatch.setattr(controller, "_receipt", drift)
    with pytest.raises((ValueError, RuntimeError)):
        controller.fence_disposable_fixture(root, expected_revision=0)
    physical = retained if change == "root_alias" else root
    database = physical / ("original.db" if change == "database" else "maintenance.db")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT phase FROM events ORDER BY revision DESC LIMIT 1").fetchone() == ("fence_requested",)
    assert (physical / "fence.fixture-receipt").exists()


@pytest.mark.parametrize("tamper", ["DELETE FROM fixture_binding", "DROP TABLE fixture_binding"])
def test_missing_binding_never_gets_automatically_recreated(tmp_path, tamper):
    root = tmp_path / "lab"
    create(root)
    with sqlite3.connect(root / "maintenance.db") as db:
        db.execute(tamper)
    before = (root / "maintenance.db").read_bytes()
    with pytest.raises(RuntimeError, match="binding"):
        controller.fence_disposable_fixture(root, expected_revision=0)
    assert (root / "maintenance.db").read_bytes() == before
    assert not (root / "fence.fixture-receipt").exists()


@pytest.mark.parametrize("change", ["content", "replacement", "symlink", "hardlink", "missing"])
def test_receipt_must_be_independently_verified_before_outcome(tmp_path, monkeypatch, change):
    root = tmp_path / "lab"
    create(root)
    original = controller._receipt
    def tamper(root, action):
        identity = original(root, action)
        receipt = root / (action + ".fixture-receipt")
        if change == "content":
            receipt.write_bytes(b"wrong result")
        elif change == "hardlink":
            (root / "receipt-alias").hardlink_to(receipt)
        else:
            receipt.rename(root / "original-receipt")
            if change == "replacement":
                receipt.write_bytes(controller.RECEIPT)
            elif change == "symlink":
                receipt.symlink_to(root / "original-receipt")
        return identity
    monkeypatch.setattr(controller, "_receipt", tamper)
    with pytest.raises((RuntimeError, OSError)):
        controller.fence_disposable_fixture(root, expected_revision=0)
    assert inspect(root)["phase"] == "fence_requested"
