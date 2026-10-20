"""Disposable end-to-end move identity review; never production media."""

from pathlib import Path

import pytest

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_move_identity_review import review_rename_identity
from app.sqlite_operation_coordinator import SQLiteOperationCoordinator
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore

STAGES = ("transient", "holding", "removal", "keep")


def _setup(tmp_path):
    paths = {}
    for stage in STAGES:
        root = tmp_path / stage
        root.mkdir()
        paths[stage] = str(root / "Movie")
    Path(paths["transient"]).mkdir()
    (Path(paths["transient"]) / "marker.txt").write_text("safe")
    database = tmp_path / "state.db"
    state = {section: {} for section in SECTIONS}
    state["first_seen"]["DISPOSABLE/Movie"] = "2024-01-01T00:00:00"
    write_offline_snapshot(state, database)
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    SQLiteOperationCoordinator(session).begin_move_with_evidence(
        "op-1", {
            "media_key": "DISPOSABLE/Movie",
            "source": paths["transient"],
            "destination": paths["holding"],
        },
    )
    return database, paths


def _review(database, paths):
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    return review_rename_identity(
        session, operation_id="op-1", media_key="DISPOSABLE/Movie",
        stage_paths=paths, source_stage="transient",
        destination_stage="holding",
    )


def _safe(result):
    assert result["authorization"] == "not_authorized"
    assert result["checkpoint_allowed"] is False
    assert result["intent_clearance"] == "blocked"
    assert result["replay_allowed"] is False
    assert result["production_activation"] == "disabled"


def test_disposable_rename_is_identity_consistent_but_not_authorized(tmp_path):
    database, paths = _setup(tmp_path)
    Path(paths["transient"]).rename(paths["holding"])
    before = database.read_bytes()
    result = _review(database, paths)
    _safe(result)
    assert result["status"] == "advisory"
    assert result["identity_assessment"] == "rename_consistent_unverified"
    assert database.read_bytes() == before
    assert (Path(paths["holding"]) / "marker.txt").read_text() == "safe"


def test_copy_and_delete_is_not_treated_as_same_directory(tmp_path):
    database, paths = _setup(tmp_path)
    Path(paths["holding"]).mkdir()
    (Path(paths["holding"]) / "marker.txt").write_text("safe")
    (Path(paths["transient"]) / "marker.txt").unlink()
    Path(paths["transient"]).rmdir()
    result = _review(database, paths)
    _safe(result)
    assert result["reason"] == "rename_identity_unverified"


@pytest.mark.parametrize("scenario", ["unmoved", "duplicate", "missing", "symlink"])
def test_uncertain_locations_never_grant_clearance(tmp_path, scenario):
    database, paths = _setup(tmp_path)
    source = Path(paths["transient"])
    dest = Path(paths["holding"])
    if scenario == "duplicate":
        dest.mkdir()
    elif scenario == "missing":
        (source / "marker.txt").unlink()
        source.rmdir()
    elif scenario == "symlink":
        dest.symlink_to(source, target_is_directory=True)
    result = _review(database, paths)
    _safe(result)
    assert result["status"] == "blocked"
