"""Protection evidence checks never grant SQLite recovery authorization."""

import pytest

from app.sqlite_jellyfin_recovery import inspect_jellyfin_protection


def _evidence():
    return {
        "available": True, "complete": True,
        "keep": False, "keep_forever": False,
        "keep_all_seasons": False, "favorite": False,
    }


def test_complete_unprotected_observation_still_blocks_clearance():
    assert inspect_jellyfin_protection(_evidence()) == (
        "unprotected_but_recovery_still_blocked"
    )


@pytest.mark.parametrize("key", [
    "keep", "keep_forever", "keep_all_seasons", "favorite"
])
def test_every_protection_flag_requires_manual_review(key):
    evidence = _evidence()
    evidence[key] = True
    assert inspect_jellyfin_protection(evidence) == "protected_manual_review_required"


@pytest.mark.parametrize("change", [
    None, {}, {"available": False}, {"complete": False},
    {"keep": "false"}, {"favorite": None}, {"keep_forever": 0},
])
def test_unavailable_incomplete_or_invalid_evidence_fails_closed(change):
    evidence = _evidence() if change is None else _evidence() | change
    if change is None:
        evidence = None
    elif change == {}:
        evidence.pop("favorite")
    with pytest.raises(RuntimeError):
        inspect_jellyfin_protection(evidence)
