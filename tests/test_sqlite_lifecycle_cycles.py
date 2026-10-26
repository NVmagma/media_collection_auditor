"""Disposable multi-cycle simulations never change persistent state."""

from copy import deepcopy
from datetime import datetime

import pytest

from app.sqlite_lifecycle_cycles import simulate_lifecycle_cycles
from app.sqlite_state import SECTIONS


KEY = "DISPOSABLE/Movie"


def _state():
    state = {section: {} for section in SECTIONS}
    state["first_seen"][KEY] = "2024-01-01T00:00:00"
    return state


def _cycle(day, signals, wait_days=7):
    return {"now": datetime(2024, 1, day), "signals": signals,
            "wait_days": wait_days}


def test_waiting_holding_removal_across_cycles_without_deletion():
    state = _state()
    original = deepcopy(state)
    result = simulate_lifecycle_cycles(
        state, media_key=KEY, initial_stage="Waiting",
        cycles=[_cycle(2, {}), _cycle(9, {}), _cycle(12, {}),
                _cycle(16, {}), _cycle(25, {})],
    )
    assert [x["decision"] for x in result["history"]] == [
        "wait", "hold", "wait", "to_removal", "delete_candidate",
    ]
    assert result["final_stage"] == "Removal"
    assert result["simulated_state"]["in_removal"][KEY] == "2024-01-16T00:00:00"
    assert result["authorization"] == "not_authorized"
    assert result["persistence"] == "none"
    assert state == original


def test_holding_rescue_preserves_keep():
    state = _state()
    result = simulate_lifecycle_cycles(
        state, media_key=KEY, initial_stage="Waiting",
        cycles=[_cycle(9, {}), _cycle(10, {"protected": True}),
                _cycle(25, {})],
    )
    assert [x["decision"] for x in result["history"]] == [
        "hold", "rescue", "none",
    ]
    assert result["final_stage"] == "Keep"
    assert KEY in result["simulated_state"]["keep_seen"]
    assert state["keep_seen"] == {}


def test_missing_jellyfin_data_does_not_transition():
    state = _state()
    result = simulate_lifecycle_cycles(
        state, media_key=KEY, initial_stage="Waiting",
        cycles=[_cycle(9, None), _cycle(10, {})],
    )
    assert [x["decision"] for x in result["history"]] == ["unknown", "hold"]
    assert result["simulated_state"]["queued"][KEY] == "2024-01-10T00:00:00"


def test_missing_tracking_clock_does_not_transition():
    state = _state()
    state["first_seen"].clear()
    result = simulate_lifecycle_cycles(
        state, media_key=KEY, initial_stage="Waiting",
        cycles=[_cycle(9, {})],
    )
    assert result["history"][0]["decision"] == "unknown"
    assert result["final_stage"] == "Waiting"


@pytest.mark.parametrize("cycles", [
    [_cycle(9, {}), _cycle(9, {})],
    [_cycle(10, {}), _cycle(9, {})],
    [{"now": datetime(2024, 1, 9), "signals": "bad", "wait_days": 7}],
    [{"now": datetime(2024, 1, 9), "signals": {}, "wait_days": -1}],
])
def test_invalid_cycles_are_rejected(cycles):
    with pytest.raises(ValueError):
        simulate_lifecycle_cycles(
            _state(), media_key=KEY, initial_stage="Waiting", cycles=cycles,
        )
