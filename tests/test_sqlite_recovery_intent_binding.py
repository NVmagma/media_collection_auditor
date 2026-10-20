"""Disposable tests for persisted operation identity and path bindings."""

from copy import deepcopy
from pathlib import Path

import pytest

from app.sqlite_recovery_intent_binding import review_bound_move
from app.sqlite_recovery_pre_move_evidence import build_pre_move_evidence

STAGES = ("transient", "holding", "removal", "keep")


def _fixture(tmp_path):
    paths = {}
    for stage in STAGES:
        root = tmp_path / stage
        root.mkdir()
        paths[stage] = str(root / "Movie")
    Path(paths["transient"]).mkdir()
    intent = {
        "id": "operation-1", "kind": "move", "phase": "intent_recorded",
        "details": {
            "media_key": "DISPOSABLE/Movie",
            "source": paths["transient"],
            "destination": paths["holding"],
            "pre_move_evidence": build_pre_move_evidence(paths["transient"]),
        },
    }
    return paths, intent


def _review(paths, intent, **overrides):
    args = dict(
        pending_intent=intent, operation_id="operation-1",
        media_key="DISPOSABLE/Movie", stage_paths=paths,
        source_stage="transient", destination_stage="holding",
    )
    args.update(overrides)
    return review_bound_move(**args)


def _blocked(result):
    assert result["authorization"] == "not_authorized"
    assert result["checkpoint_allowed"] is False
    assert result["intent_clearance"] == "blocked"
    assert result["replay_allowed"] is False
    assert result["production_activation"] == "disabled"


def test_correct_binding_still_does_not_authorize_move(tmp_path):
    paths, intent = _fixture(tmp_path)
    before = deepcopy(intent)
    Path(paths["transient"]).rename(paths["holding"])
    result = _review(paths, intent)
    _blocked(result)
    assert result["status"] == "advisory"
    assert intent == before


@pytest.mark.parametrize("field,value,reason", [
    ("operation_id", "another-operation", "operation_identity_mismatch"),
    ("media_key", "DISPOSABLE/Other", "persisted_move_binding_mismatch"),
    ("source_stage", "holding", "invalid_stage_binding"),
    ("destination_stage", "keep", "persisted_move_binding_mismatch"),
])
def test_caller_context_mismatch_blocks(tmp_path, field, value, reason):
    paths, intent = _fixture(tmp_path)
    result = _review(paths, intent, **{field: value})
    _blocked(result)
    assert result["reason"] == reason


@pytest.mark.parametrize("field,value", [
    ("id", "different-operation"),
    ("id", ""),
])
def test_persisted_operation_identity_mismatch(tmp_path, field, value):
    paths, intent = _fixture(tmp_path)
    intent[field] = value
    result = _review(paths, intent)
    _blocked(result)
    assert result["reason"] == "operation_identity_mismatch"


@pytest.mark.parametrize("field", ["source", "destination", "media_key"])
def test_tampered_persisted_binding_blocks(tmp_path, field):
    paths, intent = _fixture(tmp_path)
    intent["details"][field] = "/disposable/other"
    result = _review(paths, intent)
    _blocked(result)
    assert result["reason"] == "persisted_move_binding_mismatch"


def test_ambiguous_destination_stays_blocked(tmp_path):
    paths, intent = _fixture(tmp_path)
    Path(paths["holding"]).mkdir()
    result = _review(paths, intent)
    _blocked(result)
    assert result["status"] == "blocked"


def test_missing_evidence_stays_blocked(tmp_path):
    paths, intent = _fixture(tmp_path)
    intent["details"]["pre_move_evidence"] = {}
    result = _review(paths, intent)
    _blocked(result)
    assert result["reason"] == "invalid_pre_move_evidence"


def test_unexpected_stage_path_rejected(tmp_path):
    paths, intent = _fixture(tmp_path)
    paths["other"] = str(tmp_path / "other")
    result = _review(paths, intent)
    _blocked(result)
    assert result["reason"] == "invalid_stage_binding"
