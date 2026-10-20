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
