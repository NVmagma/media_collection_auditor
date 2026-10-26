"""Identity checks never clear interrupted media moves."""

import pytest
from datetime import datetime, timedelta, timezone

from app.sqlite_recovery_identity import inspect_move_identity, inspect_fetched_move_identity


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


NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)


def envelopes():
    return (
        {"service": "jellyfin", "title_id": "jf-1", "observed_at": NOW, "data": JF},
        {"service": "radarr", "title_id": "42", "observed_at": NOW, "data": ARR["record"]},
    )


def test_fetched_matching_evidence_still_cannot_authorize():
    jf, arr = envelopes()
    result = inspect_fetched_move_identity(
        MOVIE, jellyfin_response=jf, arr_response=arr, now=NOW
    )
    assert result["identity_verification"] == "consistent_not_authoritative"
    assert result["authorization"] == "not_authorized"


@pytest.mark.parametrize("change,reason", [
    ({"service": "sonarr"}, "response_identity_mismatch"),
    ({"title_id": "43"}, "response_identity_mismatch"),
    ({"observed_at": NOW - timedelta(minutes=2)}, "observation_not_fresh"),
    ({"observed_at": NOW + timedelta(seconds=1)}, "observation_not_fresh"),
    ({"observed_at": NOW.replace(tzinfo=None)}, "observation_timestamp_missing"),
    ({"data": {"id": 43, "imdbId": "tt1234567"}}, "arr_identity_mismatch"),
])
def test_fetched_arr_envelope_fail_closed(change, reason):
    jf, arr = envelopes()
    result = inspect_fetched_move_identity(
        MOVIE, jellyfin_response=jf, arr_response={**arr, **change}, now=NOW
    )
    assert result["reason"] == reason
    assert result["authorization"] == "not_authorized"


def test_fetched_jellyfin_response_identity_mismatch():
    jf, arr = envelopes()
    result = inspect_fetched_move_identity(
        MOVIE, jellyfin_response={**jf, "title_id": "other"},
        arr_response=arr, now=NOW
    )
    assert result["reason"] == "response_identity_mismatch"


def test_invalid_freshness_window_blocks():
    jf, arr = envelopes()
    result = inspect_fetched_move_identity(
        MOVIE, jellyfin_response=jf, arr_response=arr, now=NOW,
        max_age=timedelta(minutes=6),
    )
    assert result["reason"] == "invalid_freshness_window"
