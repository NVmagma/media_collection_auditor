"""Restart content inspection never authorizes replay or changes state."""
import json
import pytest
from tests.test_sqlite_disposable_copy_intent import lab, run
from app.sqlite_disposable_copy_inspection import inspect_disposable_copy


@pytest.mark.parametrize("fault,staging", [
    ("after_intent", "missing"), ("after_copy", "content_matches_unverified"),
    ("after_verified_checkpoint", "content_matches_unverified")])
def test_restart_reports_content_without_writing(lab, fault, staging):
    with pytest.raises(RuntimeError, match="Injected"):
        run(lab, fault_at=fault)
    before = (lab / "state.db").read_bytes()
    report = inspect_disposable_copy(root=lab)
    assert report["source_status"] == "content_matches_unverified"
    assert report["staging_status"] == staging
    assert report["status"] == "blocked"
    assert not report["recovery_authorized"] and not report["promotion_authorized"]
    assert (lab / "state.db").read_bytes() == before
    assert (lab / "transient" / "Movie A" / "payload").read_text() == "fixture"
    assert all(secret not in json.dumps(report) for secret in (str(lab), "Movie A", "copy-one", "manifest_sha256"))


@pytest.mark.parametrize("side", ["source", "staging"])
def test_changed_content_remains_blocked(lab, side):
    run(lab)
    path = lab / ("transient/Movie A" if side == "source" else ".sqlite_copy_staging/copy-one")
    (path / "payload").write_text("changed")
    report = inspect_disposable_copy(root=lab)
    assert report[side + "_status"] == "content_mismatch"
    assert report["status"] == "blocked"


def test_symlink_parent_is_not_followed(lab):
    run(lab)
    parent = lab / ".sqlite_copy_staging"
    parent.rename(lab / "retained")
    parent.symlink_to(lab / "retained", target_is_directory=True)
    assert inspect_disposable_copy(root=lab)["staging_status"] == "unavailable_or_unsafe"


def test_no_pending_copy_is_rejected(lab):
    with pytest.raises(RuntimeError, match="Pending copy required"):
        inspect_disposable_copy(root=lab)


def test_tampered_binding_stops_before_content_reads(lab, monkeypatch):
    import app.sqlite_disposable_copy_inspection as module
    from app.sqlite_audit_session import RevisionedAuditSession
    from app.state_store import GuardedSQLiteStateStore
    run(lab)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(lab / "state.db"))
    session.read_verified_snapshot()
    session.state["sqlite_pending_operations"]["details"]["source"] = "/outside/private"
    session.checkpoint()
    monkeypatch.setattr(module, "_observe", lambda *args: pytest.fail("must reject before reading content"))
    with pytest.raises(RuntimeError, match="binding invalid"):
        module.inspect_disposable_copy(root=lab)
