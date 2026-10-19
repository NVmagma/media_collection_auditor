"""Identity checks never clear interrupted media moves."""

import pytest

from app.sqlite_recovery_identity import inspect_move_identity


MOVIE = {"jellyfin_item_id": "jf-1", "jellyfin_type": "Movie",
         "arr_title_id": 42, "external_id": "tt1234567"}
JF = {"Id": "jf-1", "Type": "Movie", "ProviderIds": {"Imdb": "tt1234567"}}
ARR = {"service": "radarr", "record": {"id": 42, "imdbId": "tt1234567"}}


def test_consistent_movie_still_blocked():
    result = inspect_move_identity(MOVIE, jellyfin=JF, arr=ARR)
    assert result["identity_verification"] == "consistent_not_authoritative"
    assert result["authorization"] == "not_authorized"
    assert result["status"] == "blocked"
    assert "tt1234567" not in str(result)


@pytest.mark.parametrize("intent,jellyfin,arr,reason", [
    ({}, JF, ARR, "invalid_intent_identity"),
    (MOVIE, None, ARR, "missing_evidence"),
    (MOVIE, {**JF, "Id": "wrong"}, ARR, "jellyfin_identity_mismatch"),
    (MOVIE, JF, {**ARR, "service": "sonarr"}, "arr_service_mismatch"),
    (MOVIE, JF, {"service": "radarr", "record": {"id": 43, "imdbId": "tt1234567"}}, "arr_identity_mismatch"),
    ({**MOVIE, "external_id": ""}, JF, ARR, "shared_identity_missing"),
    (MOVIE, JF, {"service": "radarr", "record": {"id": 42, "imdbId": "tt999"}}, "shared_identity_mismatch"),
    (MOVIE, {**JF, "ProviderIds": {}}, ARR, "shared_identity_mismatch"),
])
def test_fail_closed(intent, jellyfin, arr, reason):
    result = inspect_move_identity(intent, jellyfin=jellyfin, arr=arr)
    assert result["reason"] == reason
    assert result["authorization"] == "not_authorized"


def test_consistent_series_still_blocked():
    intent = {"jellyfin_item_id": "series1", "jellyfin_type": "Series",
              "arr_title_id": 7, "external_id": "12345"}
    jellyfin = {"Id": "series1", "Type": "Series", "ProviderIds": {"Tvdb": "12345"}}
    arr = {"service": "sonarr", "record": {"id": 7, "tvdbId": 12345}}
    assert inspect_move_identity(intent, jellyfin=jellyfin, arr=arr)["identity_verification"] == "consistent_not_authoritative"
