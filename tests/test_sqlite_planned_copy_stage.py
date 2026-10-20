"""Portable staging obeys the existing planner without committing lifecycle moves."""
import pytest
from tests.test_sqlite_isolated_planned_runner import lab, FOLDER
from app.sqlite_disposable_copy_stage import stage_planned_disposable_copy
from app.sqlite_audit_session import RevisionedAuditSession
from app.state_store import GuardedSQLiteStateStore


def stage(root, bundle, **kwargs):
    return stage_planned_disposable_copy(root=root, title_folder=FOLDER, media_key=FOLDER,
                                         operation_id="planned-copy", planned_move=bundle, **kwargs)


def test_candidate_stages_without_lifecycle_commit(tmp_path):
    root, database, bundle = lab(tmp_path)
    result = stage(root, bundle)
    assert result["source_retained"] and not result["lifecycle_committed"]
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    assert FOLDER in state["first_seen"] and not state["queued"]
    assert state["sqlite_pending_operations"]["kind"] == "copy_stage"
    assert (root / "transient" / FOLDER / "payload").read_text() == "disposable"


@pytest.mark.parametrize("change", ["stale", "signals", "destination", "missing", "protected"])
def test_invalid_or_changed_plan_never_stages(tmp_path, change):
    signals = {FOLDER: {"protected": True}} if change == "protected" else None
    root, database, bundle = lab(tmp_path, signals=signals)
    kwargs = {}
    if change == "stale":
        session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
        session.checkpoint()
    elif change == "signals":
        bundle["signals_by_key"][FOLDER]["protected"] = True
    elif change == "destination":
        kwargs["destination_stage"] = "keep"
    elif change == "missing":
        del bundle["thresholds"]
    before = database.read_bytes()
    with pytest.raises((RuntimeError, ValueError)):
        stage(root, bundle, **kwargs)
    assert database.read_bytes() == before
    assert not (root / ".sqlite_copy_staging").exists()
    assert (root / "transient" / FOLDER / "payload").read_text() == "disposable"


def test_plan_binding_survives_restart_without_authority(tmp_path):
    from app.sqlite_disposable_copy_inspection import inspect_disposable_copy
    root, database, bundle = lab(tmp_path)
    stage(root, bundle)
    state, _ = GuardedSQLiteStateStore(database).load_with_revision()
    binding = state["sqlite_pending_operations"]["details"]["plan_binding"]
    assert binding == {"source_revision": 0, "source_stage": "transient",
                       "destination_stage": "holding", "observed_at": bundle["now"].isoformat()}
    before = database.read_bytes()
    report = inspect_disposable_copy(root=root)
    assert report["plan_binding_available"]
    assert report["proposed_destination_stage"] == "holding"
    assert report["status"] == "blocked" and not report["recovery_authorized"]
    assert database.read_bytes() == before


@pytest.mark.parametrize("field,value", [("source_revision", True), ("source_revision", 999),
    ("destination_stage", "removal"), ("source_stage", "keep"),
    ("observed_at", "2020-01-01T00:00:00"), ("observed_at", "bad")])
def test_invalid_persisted_plan_binding_blocks_inspection(tmp_path, monkeypatch, field, value):
    import app.sqlite_disposable_copy_inspection as module
    root, database, bundle = lab(tmp_path)
    stage(root, bundle)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    session.state["sqlite_pending_operations"]["details"]["plan_binding"][field] = value
    session.checkpoint()
    monkeypatch.setattr(module, "_observe", lambda *args: pytest.fail("invalid binding must not read content"))
    with pytest.raises(RuntimeError, match="Pending copy plan"):
        module.inspect_disposable_copy(root=root)
