"""Advanced SQLite history survives private candidate export without activation."""
import json
import os
import pytest
import app.sqlite_disposable_rollback as module
from tests.test_sqlite_disposable_copy_intent import lab
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.state_store import GuardedSQLiteStateStore

NAME = "rollback-candidate-review.json"


def advance(root):
    session = RevisionedAuditSession(GuardedSQLiteStateStore(root / "state.db"))
    session.state["queued"]["Movie A"] = session.state["first_seen"].pop("Movie A")
    session.state["arr_sync_pending"]["Movie A"] = {
        "stage": "holding", "root": "/private/holding", "monitored": False,
        "service": "radarr", "title_id": 42}
    session.state["legacy"] = {"unicode": "caf\u00e9", "nested": [1, False, None]}
    session.checkpoint()
    return session.state


def test_advanced_candidate_preserves_all_state_and_original_json(lab):
    original = lab / "auditor_state.json"
    baseline = GuardedSQLiteStateStore(lab / "state.db").load_with_revision()[0]
    original.write_text(json.dumps(baseline))
    original_bytes = original.read_bytes()
    expected = advance(lab)
    before = (lab / "state.db").read_bytes()
    report = module.export_disposable_rollback_candidate(root=lab, candidate_name=NAME)
    assert report["revision"] == 1 and report["status"] == "matching_candidate_advisory_only"
    assert not report["restore_performed"] and report["authorization"] == "not_authorized"
    assert json.loads((lab / NAME).read_bytes()) == expected
    assert original.read_bytes() == original_bytes
    assert json.loads(original_bytes) != expected
    assert (lab / "state.db").read_bytes() == before
    assert "/private" not in json.dumps(report) and "Movie A" not in json.dumps(report)
    # Re-import into a separate offline database and verify complete parity.
    write_offline_snapshot(json.loads((lab / NAME).read_bytes()), lab / "roundtrip.db")
    assert GuardedSQLiteStateStore(lab / "roundtrip.db").load_with_revision()[0] == expected
    assert module.inspect_disposable_rollback_candidate(root=lab, candidate_name=NAME)["revision"] == 1


def test_candidate_becomes_stale_after_sqlite_advances(lab):
    module.export_disposable_rollback_candidate(root=lab, candidate_name=NAME)
    advance(lab)
    report = module.inspect_disposable_rollback_candidate(root=lab, candidate_name=NAME)
    assert report["status"] == "blocked"
    assert report["reason"] == "candidate_differs_from_current_snapshot"


@pytest.mark.parametrize("kind", ["move", "arr_sync", "copy_stage"])
def test_pending_operations_block_export_and_inspection(lab, kind):
    session = RevisionedAuditSession(GuardedSQLiteStateStore(lab / "state.db"))
    session.state["sqlite_pending_operations"] = {"id": "pending", "kind": kind}
    session.checkpoint()
    for action in (module.export_disposable_rollback_candidate, module.inspect_disposable_rollback_candidate):
        with pytest.raises(RuntimeError, match="Unresolved"):
            action(root=lab, candidate_name=NAME)
    assert not (lab / NAME).exists()


@pytest.mark.parametrize("name", ["auditor_state.json", "state.db", "../rollback-candidate-x.json"])
def test_restricted_candidate_name_prevents_authoritative_overwrite(lab, name):
    with pytest.raises(ValueError):
        module.export_disposable_rollback_candidate(root=lab, candidate_name=name)


def test_existing_candidate_never_overwritten(lab):
    (lab / NAME).write_text("preserve me")
    with pytest.raises(FileExistsError):
        module.export_disposable_rollback_candidate(root=lab, candidate_name=NAME)
    assert (lab / NAME).read_text() == "preserve me"


def test_symlink_candidate_is_refused(lab):
    (lab / NAME).symlink_to(lab / "state.db")
    with pytest.raises(OSError):
        module.inspect_disposable_rollback_candidate(root=lab, candidate_name=NAME)


def test_sqlite_change_during_export_rejects_success_but_retains_artifact(lab, monkeypatch):
    original = module._read_candidate
    def read(*args):
        value = original(*args)
        advance(lab)
        return value
    monkeypatch.setattr(module, "_read_candidate", read)
    with pytest.raises(RuntimeError, match="session is stale"):
        module.export_disposable_rollback_candidate(root=lab, candidate_name=NAME)
    assert (lab / NAME).exists()
    assert GuardedSQLiteStateStore(lab / "state.db").load_with_revision()[1] == 1


def test_failed_fsync_retains_candidate_without_success(lab, monkeypatch):
    before = (lab / "state.db").read_bytes()
    def fail(fd):
        raise OSError("injected durability failure")
    monkeypatch.setattr(module.os, "fsync", fail)
    with pytest.raises(OSError, match="durability"):
        module.export_disposable_rollback_candidate(root=lab, candidate_name=NAME)
    assert (lab / NAME).exists()
    assert (lab / "state.db").read_bytes() == before


def test_duplicate_json_keys_rejected(lab):
    module.export_disposable_rollback_candidate(root=lab, candidate_name=NAME)
    raw = (lab / NAME).read_text()
    (lab / NAME).write_text('{"first_seen":{},' + raw[1:])
    with pytest.raises(ValueError, match="Duplicate"):
        module.inspect_disposable_rollback_candidate(root=lab, candidate_name=NAME)


def test_operator_export_inspect_and_stale_exit_codes(lab, capsys):
    from scripts.sqlite_disposable_rollback import main
    args = ["--root", str(lab), "--candidate-name", NAME]
    assert main(["export", *args]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["authorization"] == "not_authorized"
    assert main(["inspect", *args]) == 0
    capsys.readouterr()
    advance(lab)
    assert main(["inspect", *args]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["reason"] == "candidate_differs_from_current_snapshot"


def test_operator_failure_never_prints_private_details(lab, capsys, monkeypatch):
    import scripts.sqlite_disposable_rollback as cli
    def fail(**kwargs):
        raise RuntimeError("private Movie A /private/path token=hidden")
    monkeypatch.setattr(cli, "export_disposable_rollback_candidate", fail)
    assert cli.main(["export", "--root", str(lab), "--candidate-name", NAME]) == 2
    output = capsys.readouterr()
    assert "private" not in output.out and "hidden" not in output.out and output.err == ""
    assert json.loads(output.out)["restore_performed"] is False


def test_hardlinked_candidate_is_refused(lab):
    module.export_disposable_rollback_candidate(root=lab, candidate_name=NAME)
    os.link(lab / NAME, lab / "retained-link")
    with pytest.raises(RuntimeError, match="private candidate"):
        module.inspect_disposable_rollback_candidate(root=lab, candidate_name=NAME)
