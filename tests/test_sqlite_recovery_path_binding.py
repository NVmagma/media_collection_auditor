"""Filesystem path strings are never treated as proof of move completion."""

import pytest

from app.sqlite_recovery_path_binding import inspect_move_path_binding


INTENT = {"source": "/media/Shows/A", "destination": "/media/Shows_keep/A",
          "jellyfin_type": "Series"}
JF = {"Path": "/media/Shows_keep/A"}
ARR = {"path": "/media/Shows_keep/A"}


def check(intent=INTENT, jf=JF, arr=ARR, interpretation="destination_only_unverified"):
    return inspect_move_path_binding(
        intent, jellyfin_record=jf, arr_record=arr,
        filesystem_interpretation=interpretation,
    )


def test_matching_path_strings_are_not_authoritative():
    result = check()
    assert result["path_binding"] == "path_strings_consistent_unverified"
    assert result["authorization"] == "not_authorized"
    assert result["status"] == "blocked"
    assert "/media/" not in str(result)


@pytest.mark.parametrize("intent,jf,arr,interpretation,reason", [
    ({**INTENT, "source": "/media/../outside"}, JF, ARR, "destination_only_unverified", "invalid_intent_paths"),
    (INTENT, {"Path": "/media/Shows/A"}, ARR, "destination_only_unverified", "service_paths_disagree"),
    (INTENT, {"Path": "/elsewhere/A"}, ARR, "destination_only_unverified", "remote_path_mismatch"),
    (INTENT, JF, ARR, "both_present_ambiguous", "filesystem_not_destination_only"),
    (INTENT, {"Path": "relative"}, ARR, "destination_only_unverified", "remote_path_unavailable"),
    (INTENT, JF, {"path": "/media/Shows/A"}, "destination_only_unverified", "service_paths_disagree"),
    ({**INTENT, "jellyfin_type": "Movie"}, JF, ARR, "destination_only_unverified", "movie_file_path_requires_binding"),
])
def test_path_evidence_fail_closed(intent, jf, arr, interpretation, reason):
    result = check(intent, jf, arr, interpretation)
    assert result["reason"] == reason
    assert result["authorization"] == "not_authorized"
