"""Retained evidence is readable across scope drift without recovery rights."""
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from app import sqlite_disposable_maintenance_journal as journal
from app import sqlite_maintenance_review as review
from scripts.sqlite_maintenance_review import main


def pending(tmp_path, *, bound=False):
    root = tmp_path / "lab"
    journal.create_disposable_journal(root, bind_linux_boot=bound)
    journal.advance_disposable_journal(root, expected_revision=0, phase="fence_requested")
    return root


def evidence(root):
    return {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}


def test_changed_path_can_be_reviewed_without_rebinding_or_source_writes(tmp_path):
    original = pending(tmp_path)
    root = tmp_path / "retained"
    shutil.copytree(original, root)
    before = evidence(root)
    report = review.review_disposable_maintenance(root)
    assert report["phase"] == "fence_requested"
    assert report["revision"] == 1
    assert report["history_valid"] is True
    assert report["scope"]["path_identity"] == "changed"
    assert report["scope"]["linux_boot"] == "unbound_fixture"
    assert report["resume_authorized"] is False
    assert report["clearance_authorized"] is False
    assert report["production_authorized"] is False
    assert report["automatic_action"] == "none"
    assert evidence(root) == before
    with pytest.raises(RuntimeError, match="binding changed"):
        journal.advance_disposable_journal(root, expected_revision=1, phase="fixture_fenced")
    assert evidence(root) == before
    assert str(original) not in json.dumps(report)
    assert str(root) not in json.dumps(report)


@pytest.mark.parametrize("change", ["boot", "network", "unavailable"])
def test_runtime_drift_remains_reportable_without_accepting_scope(tmp_path, monkeypatch, change):
    boot = "17998968-809c-42c5-817a-d7e652aa7b03"
    monkeypatch.setattr(journal, "_linux_boot_id", lambda: boot)
    monkeypatch.setattr(journal, "_linux_network_namespace", lambda: "net:[1001]")
    root = pending(tmp_path, bound=True)
    before = evidence(root)
    if change == "boot":
        monkeypatch.setattr(journal, "_linux_boot_id", lambda: "e7ab85f6-24cb-4583-b886-c18109fe6ac9")
    elif change == "network":
        monkeypatch.setattr(journal, "_linux_network_namespace", lambda: "net:[2002]")
    else:
        def unavailable():
            raise RuntimeError("unavailable")
        monkeypatch.setattr(journal, "_linux_boot_id", unavailable)
        monkeypatch.setattr(journal, "_linux_network_namespace", unavailable)
    report = review.review_disposable_maintenance(root)
    assert report["history_valid"] is True
    assert report["phase"] == "fence_requested"
    assert "changed" in report["scope"].values() or "unavailable" in report["scope"].values()
    assert report["resume_authorized"] is False
    assert evidence(root) == before
    assert boot not in json.dumps(report)
    assert "net:[1001]" not in json.dumps(report)
    with pytest.raises(RuntimeError):
        journal.advance_disposable_journal(root, expected_revision=1, phase="fixture_fenced")
    assert evidence(root) == before


def test_old_fixture_schema_report_is_not_a_migration(tmp_path):
    root = pending(tmp_path)
    with sqlite3.connect(root / "maintenance.db") as db:
        db.execute("ALTER TABLE fixture_binding DROP COLUMN linux_network_namespace")
    before = evidence(root)
    report = review.review_disposable_maintenance(root)
    assert report["history_valid"] is True
    assert report["scope"]["network_namespace"] == "unavailable"
    assert report["resume_authorized"] is False
    assert evidence(root) == before


def test_invalid_history_does_not_expose_unvalidated_phase(tmp_path):
    root = pending(tmp_path)
    with sqlite3.connect(root / "maintenance.db") as db:
        db.execute("INSERT INTO events VALUES (2, 'private-invalid-phase')")
    before = evidence(root)
    report = review.review_disposable_maintenance(root)
    assert report["history_valid"] is False
    assert report["phase"] is None
    assert report["revision"] is None
    assert "private-invalid-phase" not in json.dumps(report)
    assert evidence(root) == before


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_sidecars_are_preserved_and_never_recovered(tmp_path, suffix, capsys):
    root = pending(tmp_path)
    (root / ("maintenance.db" + suffix)).write_bytes(b"retained unknown outcome")
    before = evidence(root)
    assert main(["--root", str(root)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert report["clearance_authorized"] is False
    assert evidence(root) == before


def test_source_replacement_during_review_discards_report(tmp_path, monkeypatch):
    root = pending(tmp_path)
    original = review._runtime_scope
    def replace(db):
        result = original(db)
        (root / "maintenance.db").rename(root / "retained.db")
        shutil.copyfile(root / "retained.db", root / "maintenance.db")
        return result
    monkeypatch.setattr(review, "_runtime_scope", replace)
    with pytest.raises(RuntimeError, match="changed during review"):
        review.review_disposable_maintenance(root)


def test_database_bound_and_missing_inputs_do_not_create_files(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "absent"
    assert main(["--root", str(missing)]) == 2
    assert not missing.exists()
    capsys.readouterr()
    root = pending(tmp_path)
    before = evidence(root)
    monkeypatch.setattr(review, "MAX_JOURNAL_BYTES", 1)
    assert main(["--root", str(root)]) == 2
    assert evidence(root) == before


def test_cli_zero_exit_only_means_history_was_read_not_clearance(tmp_path, capsys):
    root = pending(tmp_path)
    before = evidence(root)
    assert main(["--root", str(root)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "review_required"
    assert report["resume_authorized"] is False
    assert report["production_activation"] == "disabled"
    assert report["blockers"]
    assert evidence(root) == before
