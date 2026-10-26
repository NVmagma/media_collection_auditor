"""Evidence gate remains fail-closed on all diagnostic observations."""

import pytest

from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_recovery_evidence import evaluate_recovery_evidence


def _pending(kind, details, phase="intent_recorded"):
    return {INTENTS_KEY: {
        "id": "operation-1", "kind": kind, "phase": phase, "details": details,
    }}


def test_completed_move_observation_does_not_authorize_clearance(tmp_path):
    waiting = tmp_path / "Waiting"
    keep = tmp_path / "Keep"
    waiting.mkdir()
    keep.mkdir()
    (keep / "Movie").mkdir()
    state = _pending("move", {
        "source": str(waiting / "Movie"),
        "destination": str(keep / "Movie"),
    }, "applied_pending_reconciliation")
    report = evaluate_recovery_evidence(state)
    assert report["observation"] == "destination_present"
    assert report["authorization"] == "blocked_pending_independent_verification"
    assert INTENTS_KEY in state


def test_matching_arr_observation_does_not_authorize_clearance():
    state = _pending("arr_sync", {
        "service": "sonarr", "title_id": 12,
        "root": "/media/TV_keep", "monitored": True,
    }, "applied_pending_reconciliation")
    report = evaluate_recovery_evidence(state, arr_record={
        "id": 12, "path": "/media/TV_keep/Show", "monitored": True,
    })
    assert report["observation"] == "matching_record_unverified"
    assert report["authorization"] == "blocked_pending_independent_verification"


def test_missing_arr_record_blocks_recovery():
    state = _pending("arr_sync", {
        "service": "radarr", "title_id": 1,
        "root": "/media/Movies_keep", "monitored": False,
    })
    with pytest.raises(RuntimeError, match="unavailable"):
        evaluate_recovery_evidence(state)


def test_unsupported_and_missing_intents_are_rejected():
    for state in ({}, _pending("delete", {}), _pending("move", {}, "invalid")):
        with pytest.raises(RuntimeError):
            evaluate_recovery_evidence(state)


def test_move_rejects_unrelated_arr_record(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    with pytest.raises(RuntimeError, match="Unexpected"):
        evaluate_recovery_evidence(_pending("move", {
            "source": str(source), "destination": str(target),
        }), arr_record={"id": 1})
