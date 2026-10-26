"""Disposable read-only filesystem-to-planner integration tests."""

from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from app.sqlite_observed_checkpoint_plan import plan_from_observed_location
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_state import SECTIONS

KEY = "Shows/Example/Season 02"
WHEN = datetime(2024, 2, 1)
STAGES = ("transient", "holding", "removal", "keep")


def _fixture(tmp_path):
    state = {section: {} for section in SECTIONS}
    state["first_seen"][KEY] = "2024-01-01T00:00:00"
    state["legacy"] = {"retained": True}
    paths = {}
    for stage in STAGES:
        root = tmp_path / stage
        root.mkdir()
        paths[stage] = str(root / "Season 02")
    return state, paths


def _plan(state, paths, destination="Holding"):
    return plan_from_observed_location(
        state, media_key=KEY, source_stage="Waiting",
        destination_stage=destination, observed_at=WHEN, stage_paths=paths,
    )


def test_matching_observation_produces_advisory_detached_plan(tmp_path):
    state, paths = _fixture(tmp_path)
    Path(paths["holding"]).mkdir()
    before = deepcopy(state)
    result = _plan(state, paths)
    assert result["status"] == "advisory"
    assert result["planned_state"]["queued"][KEY] == WHEN.isoformat()
    assert result["authorization"] == "not_authorized"
    assert result["checkpoint_allowed"] is False
    assert state == before


def test_location_in_wrong_stage_blocks_transition(tmp_path):
    state, paths = _fixture(tmp_path)
    Path(paths["keep"]).mkdir()
    result = _plan(state, paths)
    assert result["status"] == "blocked"
    assert result["reason"] == "observed_stage_mismatch"
    assert result["planned_state"] is None


@pytest.mark.parametrize("stage_set", [(), ("holding", "keep")])
def test_missing_or_duplicate_media_blocks(tmp_path, stage_set):
    state, paths = _fixture(tmp_path)
    for stage in stage_set:
        Path(paths[stage]).mkdir()
    result = _plan(state, paths)
    assert result["status"] == "blocked"
    assert result["planned_state"] is None


def test_symlink_blocks_even_when_destination_exists(tmp_path):
    state, paths = _fixture(tmp_path)
    Path(paths["holding"]).mkdir()
    Path(paths["keep"]).symlink_to(paths["holding"], target_is_directory=True)
    result = _plan(state, paths)
    assert result["reason"] == "unsafe_or_unavailable_path"


def test_pending_intent_blocks_even_when_destination_matches(tmp_path):
    state, paths = _fixture(tmp_path)
    Path(paths["holding"]).mkdir()
    state[INTENTS_KEY] = {"id": "pending", "phase": "intent_recorded"}
    with pytest.raises(RuntimeError, match="Unresolved"):
        _plan(state, paths)


def test_season_identity_is_not_rewritten(tmp_path):
    state, paths = _fixture(tmp_path)
    state["first_seen"]["Shows/Example/Season 01"] = "2024-01-03T00:00:00"
    Path(paths["holding"]).mkdir()
    result = _plan(state, paths)
    assert "Shows/Example/Season 01" in result["planned_state"]["first_seen"]
    assert KEY in state["first_seen"]
