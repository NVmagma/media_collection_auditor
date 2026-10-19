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
    ({**INTENT, "jellyfin_type": "Movie"}, JF, ARR, "destination_only_unverified", "movie_file_parent_mismatch"),
])
def test_path_evidence_fail_closed(intent, jf, arr, interpretation, reason):
    result = check(intent, jf, arr, interpretation)
    assert result["reason"] == reason
    assert result["authorization"] == "not_authorized"


def test_movie_file_parent_and_radarr_directory_match_but_not_authoritative():
    intent = {**INTENT, "jellyfin_type": "Movie"}
    jf = {"Path": "/media/Shows_keep/A/Movie.mkv"}
    result = check(intent, jf, ARR)
    assert result["path_binding"] == "path_strings_consistent_unverified"
    assert result["authorization"] == "not_authorized"
    assert "/media/" not in str(result)


@pytest.mark.parametrize("jf_path,reason", [
    ("/media/Shows_keep/A", "movie_file_parent_mismatch"),
    ("/media/Shows_keep/A/subfolder/Movie.mkv", "movie_file_parent_mismatch"),
    ("/media/Shows_keep/B/Movie.mkv", "movie_file_parent_mismatch"),
    ("/media/Shows_keep/A/../B/Movie.mkv", "remote_path_unavailable"),
    ("Movie.mkv", "remote_path_unavailable"),
])
def test_movie_paths_never_guess_media_identity(jf_path, reason):
    intent = {**INTENT, "jellyfin_type": "Movie"}
    result = check(intent, {"Path": jf_path}, ARR)
    assert result["reason"] == reason
    assert result["authorization"] == "not_authorized"
