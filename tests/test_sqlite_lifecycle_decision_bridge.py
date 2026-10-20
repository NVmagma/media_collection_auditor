from datetime import datetime, timedelta

import pytest

from app.sqlite_lifecycle_decision_bridge import review_decision
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_state import SECTIONS

NOW = datetime(2026, 10, 1, 12)


def state(stage, days, key="Movie"):
    result = {name: {} for name in SECTIONS}
    result[CLOCKS[stage]][key] = (NOW - timedelta(days=days)).isoformat()
    return result


@pytest.mark.parametrize("stage,days,signals,expected", [
    ("Waiting", 30, {}, "hold"),
    ("Waiting", 1, {"keep": True}, "keep"),
    ("Waiting", 1, {"protected": True}, "keep"),
    ("Waiting", 1, {"favorite": True}, "keep"),
    ("Waiting", 1, {"disliked": True}, "hold"),
    ("Holding", 9, {}, "to_removal"),
    ("Holding", 9, {"protected": True}, "rescue"),
    ("Holding", 1, {}, "wait"),
])
def test_decision_parity(stage, days, signals, expected):
    result = review_decision(state(stage, days), "Movie", stage, NOW, 7, signals)
    assert result["candidate_action"] == expected
    assert result["action"] == expected
    assert result["authorization"] == "not_authorized"


def test_missing_jellyfin_blocks():
    result = review_decision(state("Waiting", 40), "Movie", "Waiting", NOW, 7)
    assert result["action"] == "none"
    assert "jellyfin_unavailable" in result["blockers"]


def test_removal_is_never_authorized():
    result = review_decision(state("Removal", 40), "Movie", "Removal", NOW, 7, {})
    assert result["candidate_action"] == "delete_candidate"
    assert result["action"] == "none"


def test_unresolved_intent_blocks():
    snapshot = state("Holding", 10)
    snapshot["sqlite_pending_operations"] = {"id": "pending"}
    result = review_decision(snapshot, "Movie", "Holding", NOW, 7, {"keep": True})
    assert result["action"] == "none"


def test_duplicate_clock_blocks():
    snapshot = state("Waiting", 10)
    snapshot["queued"]["Movie"] = NOW.isoformat()
    result = review_decision(snapshot, "Movie", "Waiting", NOW, 7, {})
    assert "missing_or_conflicting_clock" in result["blockers"]


def test_tv_key_and_favorite_switch():
    snapshot = state("Waiting", 1, "TV/Example")
    result = review_decision(snapshot, "TV/Example", "Waiting", NOW, 7,
                             {"favorite": True}, False)
    assert result["action"] == "wait"
