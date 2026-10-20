from datetime import datetime, timedelta

import pytest

from app.sqlite_jellyfin_signal_contract import review_jellyfin_observation

NOW = datetime(2026, 10, 20, 12)
KEY = "Movies/Movie"
SIGNALS = {"played": False, "favorite": False, "disliked": False,
           "keep": False, "keep_all": False, "protected": False}


def observation(**changes):
    value = {"media_key": KEY, "observed_at": NOW,
             "coverage_complete": True, "request_succeeded": True,
             "signals": dict(SIGNALS)}
    value.update(changes)
    return value


def review(value):
    return review_jellyfin_observation(
        observation=value, media_key=KEY, now=NOW)


def test_complete_observation_is_still_untrusted_and_nonauthorizing():
    result = review(observation())
    assert result["status"] == "shape_valid_untrusted"
    assert result["signals"] == SIGNALS
    assert result["authorization"] == "not_authorized"
    assert result["freshness_independently_verified"] is False


@pytest.mark.parametrize("value,expected", [
    (None, "jellyfin_observation_unavailable"),
    (observation(coverage_complete=False), "jellyfin_coverage_unverified"),
    (observation(request_succeeded=False), "jellyfin_request_unverified"),
    (observation(media_key="Other"), "jellyfin_identity_unverified"),
    (observation(observed_at=NOW - timedelta(seconds=61)), "jellyfin_observation_not_current"),
    (observation(observed_at=NOW + timedelta(seconds=1)), "jellyfin_observation_not_current"),
    (observation(signals={"keep": True}), "jellyfin_signals_incomplete"),
    (observation(signals={**SIGNALS, "keep": 1}), "jellyfin_signals_incomplete"),
    (observation(signals={**SIGNALS, "protected": True}), "jellyfin_protection_inconsistent"),
])
def test_unreliable_observations_block(value, expected):
    result = review(value)
    assert result["status"] == "blocked"
    assert expected in result["blockers"]
    assert result["signals"] is None


def test_observation_is_detached_from_caller():
    value = observation()
    result = review(value)
    value["signals"]["keep"] = True
    assert result["signals"]["keep"] is False


def test_invalid_age_limit_rejected():
    with pytest.raises(ValueError):
        review_jellyfin_observation(
            observation=observation(), media_key=KEY, now=NOW,
            maximum_age_seconds=True)
