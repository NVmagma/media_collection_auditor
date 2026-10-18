"""Combined SQLite recovery gate tests with disposable media paths."""

import pytest

from app.sqlite_combined_recovery import inspect_combined_recovery
from app.sqlite_operation_coordinator import INTENTS_KEY


def _jellyfin(**changes):
    return {
        "available": True, "complete": True, "keep": False,
        "keep_forever": False, "keep_all_seasons": False,
        "favorite": False,
    } | changes


def _state(kind, details):
    return {INTENTS_KEY: {
        "id": "op-1", "kind": kind, "details": details,
        "phase": "applied_pending_reconciliation",
    }}


def test_move_observed_with_complete_jellyfin_still_blocked(tmp_path):
    source_parent = tmp_path / "Waiting"
    target_parent = tmp_path / "Keep"
    source_parent.mkdir()
    target_parent.mkdir()
    (target_parent / "Movie").mkdir()
    report = inspect_combined_recovery(_state("move", {
        "source": str(source_parent / "Movie"),
        "destination": str(target_parent / "Movie"),
    }), jellyfin_evidence=_jellyfin())
    assert report["observation"] == "destination_present"
    assert report["authorization"] == "blocked_pending_independent_verification"
    assert report["jellyfin_protection"] == "unprotected_but_recovery_still_blocked"


def test_protected_media_never_authorizes_recovery(tmp_path):
    source_parent = tmp_path / "Waiting"
    target_parent = tmp_path / "Keep"
    source_parent.mkdir()
    target_parent.mkdir()
    (target_parent / "Movie").mkdir()
    report = inspect_combined_recovery(_state("move", {
        "source": str(source_parent / "Movie"),
        "destination": str(target_parent / "Movie"),
    }), jellyfin_evidence=_jellyfin(keep_forever=True))
    assert report["jellyfin_protection"] == "protected_manual_review_required"
    assert report["authorization"].startswith("blocked")


@pytest.mark.parametrize("evidence", [None, {}, {"available": False}])
def test_jellyfin_outage_blocks_even_matching_arr_record(evidence):
    state = _state("arr_sync", {
        "service": "radarr", "title_id": 42,
        "root": "/media/Movies_keep", "monitored": False,
    })
    record = {
        "id": 42, "path": "/media/Movies_keep/Movie",
        "monitored": False,
    }
    with pytest.raises(RuntimeError, match="Jellyfin"):
        inspect_combined_recovery(state, jellyfin_evidence=evidence, arr_record=record)


def test_matching_arr_and_jellyfin_still_not_authorized():
    report = inspect_combined_recovery(_state("arr_sync", {
        "service": "sonarr", "title_id": 17,
        "root": "/media/TV_keep", "monitored": True,
    }), jellyfin_evidence=_jellyfin(), arr_record={
        "id": 17, "path": "/media/TV_keep/Show",
        "monitored": True,
    })
    assert report["observation"] == "matching_record_unverified"
    assert report["authorization"] == "blocked_pending_independent_verification"


def test_arr_missing_still_fails_with_jellyfin_available():
    with pytest.raises(RuntimeError, match="Arr response unavailable"):
        inspect_combined_recovery(_state("arr_sync", {
            "service": "radarr", "title_id": 42,
            "root": "/media/Movies_keep", "monitored": False,
        }), jellyfin_evidence=_jellyfin())
