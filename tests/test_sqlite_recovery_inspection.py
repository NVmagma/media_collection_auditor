"""Recovery inspection must never authorize automatic replay or deletion."""

import pytest

from app.sqlite_recovery_inspection import inspect_pending_operation
from app.sqlite_operation_coordinator import INTENTS_KEY


def _intent(kind, details, phase="intent_recorded"):
    return {INTENTS_KEY: {
        "id": "op-1", "kind": kind, "details": details, "phase": phase,
    }}


def test_pending_move_source_present_still_requires_reconciliation(tmp_path):
    waiting = tmp_path / "Waiting"
    keep = tmp_path / "Keep"
    waiting.mkdir()
    keep.mkdir()
    (waiting / "Movie").mkdir()
    state = _intent("move", {
        "source": str(waiting / "Movie"), "destination": str(keep / "Movie")
    })
    report = inspect_pending_operation(state)
    assert report["observation"] == "not_started"
    assert report["decision"] == "manual_reconciliation_required"
    assert state[INTENTS_KEY]["phase"] == "intent_recorded"


def test_destination_present_is_not_automatic_success(tmp_path):
    waiting = tmp_path / "Waiting"
    keep = tmp_path / "Keep"
    waiting.mkdir()
    keep.mkdir()
    (keep / "Movie").mkdir()
    report = inspect_pending_operation(_intent("move", {
        "source": str(waiting / "Movie"), "destination": str(keep / "Movie")
    }, "applied_pending_reconciliation"))
    assert report["observation"] == "destination_present"
    assert report["decision"] == "manual_reconciliation_required"


def test_arr_sync_never_assumes_external_success():
    report = inspect_pending_operation(_intent("arr_sync", {
        "title": "Movie", "stage": "keep"
    }))
    assert report["observation"] == "external_state_unverified"
    assert report["decision"] == "manual_reconciliation_required"


def test_missing_or_malformed_intents_fail_closed():
    for state in ({}, {INTENTS_KEY: None}, _intent("delete", {}),
                  _intent("move", {}, "unknown"),
                  {INTENTS_KEY: {"kind": "move"}}):
        with pytest.raises(RuntimeError):
            inspect_pending_operation(state)


def test_ambiguous_move_is_not_classified_as_success(tmp_path):
    source = tmp_path / "Waiting"
    target = tmp_path / "Keep"
    source.mkdir()
    target.mkdir()
    with pytest.raises(RuntimeError, match="Ambiguous"):
        inspect_pending_operation(_intent("move", {
            "source": str(source), "destination": str(target)
        }))
