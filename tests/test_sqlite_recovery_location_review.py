"""Disposable recovery evidence reviews remain non-authorizing."""

from copy import deepcopy
from pathlib import Path

import pytest

from app.sqlite_recovery_location_review import review_interrupted_move
from app.sqlite_recovery_pre_move_evidence import build_pre_move_evidence

STAGES = ("transient", "holding", "removal", "keep")


def _setup(tmp_path):
    paths = {}
    for stage in STAGES:
        root = tmp_path / stage
        root.mkdir()
        paths[stage] = str(root / "title")
    Path(paths["transient"]).mkdir()
    intent = {"kind": "move", "phase": "intent_recorded",
              "details": {"pre_move_evidence": build_pre_move_evidence(paths["transient"])}}
    return paths, intent


def _review(paths, intent):
    return review_interrupted_move(
        pending_intent=intent, stage_paths=paths, expected_destination="holding"
    )


def _assert_safe(result):
    assert result["authorization"] == "not_authorized"
    assert result["checkpoint_allowed"] is False
    assert result["intent_clearance"] == "blocked"
    assert result["replay_allowed"] is False


def test_source_still_present_does_not_imply_move(tmp_path):
    paths, intent = _setup(tmp_path)
    _assert_safe(_review(paths, intent))
    assert _review(paths, intent)["reason"] == "destination_mismatch"


def test_missing_everywhere_blocks(tmp_path):
    paths, intent = _setup(tmp_path)
    Path(paths["transient"]).rmdir()
    result = _review(paths, intent)
    _assert_safe(result)
    assert result["reason"] == "media_missing"


def test_duplicate_location_blocks(tmp_path):
    paths, intent = _setup(tmp_path)
    Path(paths["holding"]).mkdir()
    result = _review(paths, intent)
    _assert_safe(result)
    assert result["reason"] == "media_ambiguous"


def test_relocated_directory_still_not_trusted(tmp_path):
    paths, intent = _setup(tmp_path)
    before = deepcopy(intent)
    Path(paths["transient"]).rename(paths["holding"])
    result = _review(paths, intent)
    _assert_safe(result)
    assert result["status"] == "advisory"
    assert result["fingerprint_binding"] in (
        "unverified", "metadata_consistent_unverified"
    )
    assert intent == before


@pytest.mark.parametrize("mutation", [
    lambda intent: intent.update(kind="arr_sync"),
    lambda intent: intent.update(phase="cleared"),
    lambda intent: intent["details"].update(pre_move_evidence={}),
])
def test_invalid_intent_or_evidence_fails_closed(tmp_path, mutation):
    paths, intent = _setup(tmp_path)
    mutation(intent)
    result = _review(paths, intent)
    _assert_safe(result)
    assert result["status"] == "blocked"


def test_symlink_destination_blocks(tmp_path):
    paths, intent = _setup(tmp_path)
    Path(paths["holding"]).symlink_to(paths["transient"], target_is_directory=True)
    result = _review(paths, intent)
    _assert_safe(result)
    assert result["reason"] == "unsafe_or_unavailable_path"
