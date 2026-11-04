"""Validate Jellyfin observation shape for tracking advisory planning.

An observation is caller-provided and NEVER proves that Jellyfin was queried,
that all users/libraries were covered, or that protection is current.
Production execution must independently establish those properties.
"""

from __future__ import annotations

from datetime import datetime, timedelta

SIGNAL_FIELDS = frozenset({
    "played", "favorite", "disliked", "keep", "keep_all", "protected",
})


def review_jellyfin_observation(*, observation, media_key, now,
                               maximum_age_seconds=60):
    """Fail closed on absent, incomplete, old, or contradictory observations."""
    blockers = []
    if not isinstance(now, datetime) or now.tzinfo is not None:
        raise ValueError("Naive observation clock required")
    if type(maximum_age_seconds) is not int or maximum_age_seconds < 0:
        raise ValueError("Invalid observation age limit")
    if not isinstance(media_key, str) or not media_key:
        raise ValueError("Media key required")
    if not isinstance(observation, dict):
        blockers.append("jellyfin_observation_unavailable")
        observation = {}
    timestamp = observation.get("observed_at")
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is not None:
        blockers.append("jellyfin_observation_time_unavailable")
    elif timestamp > now or now - timestamp > timedelta(seconds=maximum_age_seconds):
        blockers.append("jellyfin_observation_not_current")
    if observation.get("media_key") != media_key:
        blockers.append("jellyfin_identity_unverified")
    if observation.get("coverage_complete") is not True:
        blockers.append("jellyfin_coverage_unverified")
    if observation.get("request_succeeded") is not True:
        blockers.append("jellyfin_request_unverified")
    signals = observation.get("signals")
    if (not isinstance(signals, dict)
            or not SIGNAL_FIELDS.issubset(signals)
            or any(type(signals[field]) is not bool for field in SIGNAL_FIELDS)):
        blockers.append("jellyfin_signals_incomplete")
        signals = None
    elif signals["protected"] and not signals["keep_all"]:
        blockers.append("jellyfin_protection_inconsistent")
    return {
        "status": "blocked" if blockers else "shape_valid_untrusted",
        "blockers": blockers,
        "signals": dict(signals) if not blockers else None,
        "authorization": "not_authorized",
        "freshness_independently_verified": False,
        "production_activation": "disabled",
        "read_only": True,
    }
