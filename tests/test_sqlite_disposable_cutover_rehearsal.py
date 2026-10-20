"""One retained fixture spans migration, two checkpoints, export and JSON restart."""
import json
import pytest
import app.sqlite_disposable_cutover_rehearsal as module
from scripts.sqlite_disposable_cutover_rehearsal import main


def test_complete_synthetic_rehearsal(tmp_path):
    root = tmp_path / "new-lab"
    report = module.rehearse_disposable_cutover(root=root)
    assert report["revision"] == 2
    assert report["status"] == "rehearsal_passed_advisory_only"
    assert report["stale_candidate_blocked"] and report["json_restart_parity"]
    assert report["production_activation"] == "disabled"
    assert not report["production_restore_performed"] and not report["media_actions_performed"]
    original = json.loads((root / "original.json").read_bytes())
    current = json.loads((root / "rollback-candidate-current.json").read_bytes())
    assert original != current
    assert current["legacy"]["newer_history"] == "second checkpoint"
    assert len(current["arr_sync_pending"]) == 2
    assert str(root) not in json.dumps(report)


def test_existing_directory_is_never_reused(tmp_path):
    preserved = tmp_path / "private.txt"
    preserved.write_text("preserve")
    with pytest.raises(FileExistsError):
        module.rehearse_disposable_cutover(root=tmp_path)
    assert preserved.read_text() == "preserve"
    assert not (tmp_path / "state.db").exists()


def test_restart_failure_preserves_all_recovery_artifacts(tmp_path, monkeypatch, capsys):
    def fail(*args):
        raise RuntimeError("private path /secret token=hidden")
    monkeypatch.setattr(module, "_json_restart", fail)
    root = tmp_path / "failed-lab"
    assert main(["--root", str(root)]) == 2
    output = capsys.readouterr().out
    assert "/secret" not in output and "hidden" not in output
    assert json.loads(output)["artifacts_retained"]
    assert (root / "state.db").is_file()
    assert (root / "rollback-candidate-current.json").is_file()
    assert (root / "original.json").read_bytes() == (root / "original.backup.json").read_bytes()


def test_alias_parent_is_refused(tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        module.rehearse_disposable_cutover(root=alias / "lab")
    assert not (tmp_path / "lab").exists()


def test_checkpoint_failure_stops_before_export(tmp_path, monkeypatch):
    from app.state_store import GuardedSQLiteStateStore
    def fail(*args):
        raise RuntimeError("injected checkpoint failure")
    monkeypatch.setattr(GuardedSQLiteStateStore, "save_if_revision", fail)
    root = tmp_path / "checkpoint-failure"
    with pytest.raises(RuntimeError, match="checkpoint failure"):
        module.rehearse_disposable_cutover(root=root)
    assert (root / "original.json").read_bytes() == (root / "original.backup.json").read_bytes()
    assert not list(root.glob("rollback-candidate-*.json"))
    assert GuardedSQLiteStateStore(root / "state.db").load_with_revision()[1] == 0


def test_cli_success_remains_non_authorizing(tmp_path, capsys):
    assert main(["--root", str(tmp_path / "cli-lab")]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "rehearsal_passed_advisory_only"
    assert report["authorization"] == "not_authorized"
    assert report["production_activation"] == "disabled"
