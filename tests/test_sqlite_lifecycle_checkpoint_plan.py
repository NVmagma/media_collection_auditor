"""Safety tests for advisory lifecycle checkpoint plans."""

from copy import deepcopy
from datetime import datetime

import pytest

from app.sqlite_lifecycle_checkpoint_plan import plan_lifecycle_checkpoint
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_state import SECTIONS

KEY = "Shows/Example/Season 02"
WHEN = datetime(2024, 2, 1)


def _state():
    state = {section: {} for section in SECTIONS}
    state["first_seen"][KEY] = "2024-01-01T00:00:00"
    state["legacy"] = {"nested": [None, True, 3]}
    return state


def _plan(state, source="Waiting", destination="Holding", observation="unique"):
    return plan_lifecycle_checkpoint(
        state, media_key=KEY, source_stage=source,
        destination_stage=destination, observed_at=WHEN,
        destination_observation=observation,
    )


@pytest.mark.parametrize("destination,section", [
    ("Holding", "queued"), ("Keep", "keep_seen"),
])
def test_advisory_plan_does_not_change_original(destination, section):
    state = _state()
    before = deepcopy(state)
    result = _plan(state, destination=destination)
    assert result["status"] == "advisory"
    assert result["checkpoint_allowed"] is False
    assert result["authorization"] == "not_authorized"
    assert result["planned_state"][section][KEY] == WHEN.isoformat()
    assert KEY not in result["planned_state"]["first_seen"]
    assert result["planned_state"]["legacy"] == before["legacy"]
    assert state == before


@pytest.mark.parametrize("observation", ["missing", "ambiguous"])
def test_unverified_destination_blocks_plan(observation):
    result = _plan(_state(), observation=observation)
    assert result["status"] == "blocked"
    assert result["planned_state"] is None


def test_unresolved_intent_blocks_plan():
    state = _state()
    state[INTENTS_KEY] = {"id": "pending", "phase": "intent_recorded"}
    with pytest.raises(RuntimeError, match="Unresolved"):
        _plan(state)


def test_conflicting_stage_clocks_block_plan():
    state = _state()
    state["queued"][KEY] = "2024-01-02T00:00:00"
    with pytest.raises(RuntimeError, match="Conflicting"):
        _plan(state)


def test_missing_source_clock_blocks_plan():
    state = _state()
    state["first_seen"].clear()
    with pytest.raises(RuntimeError, match="unavailable"):
        _plan(state)


@pytest.mark.parametrize("source,destination", [
    ("Removal", "Holding"), ("Keep", "Removal"),
    ("Waiting", "Removal"), ("Waiting", "Waiting"),
])
def test_unsupported_transitions_rejected(source, destination):
    with pytest.raises(ValueError, match="Unsupported"):
        _plan(_state(), source=source, destination=destination)


def test_season_identity_and_other_season_are_preserved():
    state = _state()
    other = "Shows/Example/Season 01"
    state["first_seen"][other] = "2024-01-03T00:00:00"
    result = _plan(state)
    assert other in result["planned_state"]["first_seen"]
    assert KEY in state["first_seen"]
