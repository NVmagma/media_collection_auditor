"""Durable portable-copy phases never authorize cleanup or automatic replay."""
import pytest

import app.sqlite_disposable_copy_stage as module
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


@pytest.fixture
def lab(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    (root / ".sqlite_disposable_rehearsal").write_text("DISPOSABLE ONLY\n")
    (root / "transient" / "Movie A").mkdir(parents=True)
    (root / "transient" / "Movie A" / "payload").write_text("fixture")
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["Movie A"] = "2024-01-01T00:00:00"
    write_offline_snapshot(state, root / "state.db")
    return root


def run(root, **kwargs):
    return module.stage_disposable_copy_with_intent(
        root=root, title_folder="Movie A", media_key="Movie A", operation_id="copy-one", **kwargs)


def state(root):
    return GuardedSQLiteStateStore(root / "state.db").load_with_revision()[0]


def test_copy_intent_precedes_writes_and_success_remains_pending(lab, monkeypatch):
    original = module._copy_tree
    def check_intent(source, destination):
        pending = state(lab)["sqlite_pending_operations"]
        assert pending["kind"] == "copy_stage"
        assert pending["details"]["copy_phase"] == "prepared"
        original(source, destination)
    monkeypatch.setattr(module, "_copy_tree", check_intent)
    result = run(lab)
    assert result["status"] == "copy_verified_pending_review"
    assert result["source_retained"] is True
    assert result["promotion_authorized"] is False
    after = state(lab)
    assert after["first_seen"]["Movie A"] == "2024-01-01T00:00:00"
    assert not after["queued"] and not after["arr_sync_pending"]
    assert after["sqlite_pending_operations"]["details"]["copy_phase"] == "verified_source_retained"
    assert after["sqlite_pending_operations"]["phase"] == "applied_pending_reconciliation"


@pytest.mark.parametrize("fault,phase", [("after_intent", "prepared"), ("after_copy", "prepared"),
                                         ("after_verified_checkpoint", "verified_source_retained")])
def test_crash_reopens_as_pending_without_replay(lab, fault, phase):
    with pytest.raises(RuntimeError, match="Injected copy crash"):
        run(lab, fault_at=fault)
    assert state(lab)["sqlite_pending_operations"]["details"]["copy_phase"] == phase
    before = (lab / "state.db").read_bytes()
    with pytest.raises(RuntimeError, match="Unresolved"):
        run(lab)
    assert (lab / "state.db").read_bytes() == before
    assert (lab / "transient" / "Movie A" / "payload").read_text() == "fixture"


def test_failed_intent_checkpoint_never_starts_copy(lab, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("checkpoint failed")
    monkeypatch.setattr(GuardedSQLiteStateStore, "save_if_revision", fail)
    monkeypatch.setattr(module, "_copy_tree", lambda *args: pytest.fail("copy must not run"))
    before = (lab / "state.db").read_bytes()
    with pytest.raises(RuntimeError, match="checkpoint failed"):
        run(lab)
    assert (lab / "state.db").read_bytes() == before
    assert not (lab / ".sqlite_copy_staging").exists()


def test_copy_failure_preserves_intent_source_and_partial_stage(lab, monkeypatch):
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(module, "_copy_tree", fail)
    with pytest.raises(OSError, match="disk full"):
        run(lab)
    assert state(lab)["sqlite_pending_operations"]["details"]["copy_phase"] == "prepared"
    assert (lab / "transient" / "Movie A" / "payload").exists()
    assert (lab / ".sqlite_copy_staging" / "copy-one").is_dir()


@pytest.mark.parametrize("commit_before_error", [False, True])
def test_uncertain_verified_checkpoint_always_retains_pending_source(lab, monkeypatch, commit_before_error):
    original = GuardedSQLiteStateStore.save_if_revision
    writes = 0
    def uncertain(self, snapshot, revision):
        nonlocal writes
        writes += 1
        if writes == 2:
            if commit_before_error:
                original(self, snapshot, revision)
            raise RuntimeError("uncertain copy checkpoint")
        return original(self, snapshot, revision)
    monkeypatch.setattr(GuardedSQLiteStateStore, "save_if_revision", uncertain)
    with pytest.raises(RuntimeError, match="uncertain copy checkpoint"):
        run(lab)
    pending = state(lab)["sqlite_pending_operations"]
    assert pending["details"]["copy_phase"] == ("verified_source_retained" if commit_before_error else "prepared")
    assert (lab / "transient" / "Movie A" / "payload").read_text() == "fixture"
    with pytest.raises(RuntimeError, match="Unresolved"):
        run(lab)


def test_pending_copy_report_is_read_only_and_redacted(lab):
    import json
    from app.sqlite_recovery_report import inspect_pending_recovery_status
    from app.sqlite_recovery_inspection import inspect_pending_operation
    run(lab)
    before = (lab / "state.db").read_bytes()
    report = inspect_pending_recovery_status(lab / "state.db")
    assert report["status"] == "blocked"
    assert report["copy_phase"] == "verified_source_retained"
    assert report["blocker"] == "portable_copy_recovery_not_authorized"
    assert report["production_activation"] == "disabled"
    assert str(lab) not in json.dumps(report)
    assert "manifest_sha256" not in json.dumps(report)
    assert inspect_pending_operation(state(lab))["decision"] == "manual_reconciliation_required"
    assert (lab / "state.db").read_bytes() == before
