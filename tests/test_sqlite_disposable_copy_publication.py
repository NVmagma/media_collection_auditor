"""Optional no-replace publication never retires source or commits lifecycle."""
import sys
import pytest
import app.sqlite_disposable_copy_publication as module
from tests.test_sqlite_isolated_planned_runner import lab, FOLDER
from tests.test_sqlite_planned_copy_stage import stage
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_copy_inspection import inspect_disposable_copy
from app.state_store import GuardedSQLiteStateStore


def prepared(tmp_path):
    root, database, bundle = lab(tmp_path)
    stage(root, bundle)
    return root, database


def test_unsupported_atomic_publication_retains_source_and_staging(tmp_path, monkeypatch):
    root, database = prepared(tmp_path)
    def unsupported(*args):
        raise RuntimeError("Atomic no-replace rename unsupported")
    monkeypatch.setattr(module, "rename_directory_noreplace_at", unsupported)
    with pytest.raises(RuntimeError, match="unsupported"):
        module.publish_disposable_copy(root=root)
    assert (root / "transient" / FOLDER / "payload").read_text() == "disposable"
    assert (root / ".sqlite_copy_staging" / "planned-copy" / "payload").exists()
    assert not (root / "holding" / FOLDER).exists()
    pending = GuardedSQLiteStateStore(database).load_with_revision()[0]["sqlite_pending_operations"]
    assert pending["details"]["publication"]["phase"] == "prepared"
    with pytest.raises(RuntimeError, match="already attempted"):
        module.publish_disposable_copy(root=root)


def test_destination_is_never_overwritten(tmp_path):
    root, database = prepared(tmp_path)
    (root / "holding" / FOLDER).mkdir()
    (root / "holding" / FOLDER / "preserved").write_text("external title")
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="occupied"):
        module.publish_disposable_copy(root=root)
    assert (root / "holding" / FOLDER / "preserved").read_text() == "external title"
    assert database.read_bytes() == before


def test_publication_intent_crash_is_not_replayed(tmp_path):
    root, _ = prepared(tmp_path)
    with pytest.raises(RuntimeError, match="after intent"):
        module.publish_disposable_copy(root=root, fault_at="after_intent")
    report = inspect_disposable_copy(root=root)
    assert report["publication_phase"] == "prepared" and report["published_status"] == "missing"
    assert report["status"] == "blocked"
    with pytest.raises(RuntimeError, match="already attempted"):
        module.publish_disposable_copy(root=root)


@pytest.mark.skipif(sys.platform != "linux", reason="Actual Linux no-replace publication required")
@pytest.mark.parametrize("fault,phase", [(None, "published_source_retained"),
    ("after_publication", "prepared"), ("after_checkpoint", "published_source_retained")])
def test_actual_publication_preserves_source_and_pending_tracking(tmp_path, fault, phase):
    root, database = prepared(tmp_path)
    if fault:
        with pytest.raises(RuntimeError, match="Injected publication crash"):
            module.publish_disposable_copy(root=root, fault_at=fault)
    else:
        result = module.publish_disposable_copy(root=root)
        assert not result["lifecycle_committed"] and not result["intent_cleared"]
    assert (root / "transient" / FOLDER / "payload").read_text() == "disposable"
    assert (root / "holding" / FOLDER / "payload").read_text() == "disposable"
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert FOLDER in state["first_seen"] and not state["queued"] and not state["arr_sync_pending"]
    report = inspect_disposable_copy(root=root)
    assert report["publication_phase"] == phase
    assert report["published_status"] == "content_matches_unverified"
    assert report["status"] == "blocked" and not report["recovery_authorized"]
    with pytest.raises(RuntimeError, match="already attempted"):
        module.publish_disposable_copy(root=root)


def test_actual_capability_either_publishes_or_preserves_prepared_copy(tmp_path):
    import errno
    root, database = prepared(tmp_path)
    try:
        result = module.publish_disposable_copy(root=root)
    except RuntimeError as exc:
        if sys.platform != "linux":
            assert str(exc) == "Atomic no-replace rename requires Linux"
        else:
            assert str(exc) == "Atomic no-replace rename unsupported"
            assert isinstance(exc.__cause__, OSError)
            assert exc.__cause__.errno in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP)
        assert (root / ".sqlite_copy_staging" / "planned-copy" / "payload").read_text() == "disposable"
        assert not (root / "holding" / FOLDER).exists()
        phase = "prepared"
    else:
        assert result["status"] == "published_source_retained_pending_review"
        assert (root / "holding" / FOLDER / "payload").read_text() == "disposable"
        phase = "published_source_retained"
    assert (root / "transient" / FOLDER / "payload").read_text() == "disposable"
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert FOLDER in state["first_seen"] and not state["queued"]
    assert state["sqlite_pending_operations"]["details"]["publication"]["phase"] == phase


def test_changed_staged_bytes_do_not_create_publication_marker(tmp_path, monkeypatch):
    root, database = prepared(tmp_path)
    before = database.read_bytes()
    inspect = module.inspect_disposable_copy
    def review(**kwargs):
        result = inspect(**kwargs)
        (root / ".sqlite_copy_staging" / "planned-copy" / "payload").write_text("changed after review")
        return result
    monkeypatch.setattr(module, "inspect_disposable_copy", review)
    with pytest.raises(RuntimeError, match="content differs"):
        module.publish_disposable_copy(root=root)
    assert database.read_bytes() == before
    assert not (root / "holding" / FOLDER).exists()
    assert (root / "transient" / FOLDER / "payload").read_text() == "disposable"


def test_missing_plan_binding_is_not_permission_to_publish(tmp_path):
    root, database = prepared(tmp_path)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    del session.state["sqlite_pending_operations"]["details"]["plan_binding"]
    session.checkpoint()
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="plan-bound"):
        module.publish_disposable_copy(root=root)
    assert database.read_bytes() == before
    assert not (root / "holding" / FOLDER).exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Actual Linux no-replace race required")
def test_actual_publication_rejects_destination_created_after_intent(tmp_path, monkeypatch):
    root, database = prepared(tmp_path)
    rename = module.rename_directory_noreplace_at
    def race(source_parent, source_name, destination_parent, destination_name):
        (root / "holding" / FOLDER).mkdir()
        (root / "holding" / FOLDER / "preserved").write_text("external destination")
        return rename(source_parent, source_name, destination_parent, destination_name)
    monkeypatch.setattr(module, "rename_directory_noreplace_at", race)
    with pytest.raises(FileExistsError):
        module.publish_disposable_copy(root=root)
    assert (root / "holding" / FOLDER / "preserved").read_text() == "external destination"
    assert (root / ".sqlite_copy_staging" / "planned-copy" / "payload").read_text() == "disposable"
    assert (root / "transient" / FOLDER / "payload").read_text() == "disposable"
    pending = GuardedSQLiteStateStore(database).load_with_revision()[0]["sqlite_pending_operations"]
    assert pending["details"]["publication"]["phase"] == "prepared"
