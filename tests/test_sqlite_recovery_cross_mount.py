"""Cross-container mount reports are advisory, never a recovery grant."""
import pytest

from app.sqlite_recovery_cross_mount import inspect_cross_container_mount_evidence

LOCAL = {
    "status": "blocked",
    "authorization": "not_authorized",
    "mount_identity": "local_namespace_observed_unverified",
    "reason": "cross_container_identity_not_established",
}


def observations():
    return {name: dict(LOCAL) for name in ("auditor", "jellyfin", "arr")}


def test_three_consistent_service_reports_do_not_prove_shared_mount():
    result = inspect_cross_container_mount_evidence(observations())
    assert result["reason"] == "independent_mount_identity_not_established"
    assert result["shared_mount_identity"] == "unverified"
    assert result["authorization"] == "not_authorized"
    assert result["reconciliation"] == "disabled"


@pytest.mark.parametrize("service", ["auditor", "jellyfin", "arr"])
@pytest.mark.parametrize("field,value", [
    ("status", "ready"),
    ("authorization", "authorized"),
    ("mount_identity", "unverified"),
    ("reason", "no_matching_mount"),
])
def test_untrusted_service_report_fails_closed(service, field, value):
    data = observations()
    data[service][field] = value
    result = inspect_cross_container_mount_evidence(data)
    assert result["reason"] == "service_observation_unverified"
    assert result["authorization"] == "not_authorized"


@pytest.mark.parametrize("data", [
    None, {}, {"auditor": dict(LOCAL)},
    {"auditor": dict(LOCAL), "jellyfin": dict(LOCAL),
     "arr": dict(LOCAL), "other": dict(LOCAL)},
])
def test_missing_or_extra_service_reports_fail_closed(data):
    result = inspect_cross_container_mount_evidence(data)
    assert result["reason"] == "service_observations_missing"
    assert result["authorization"] == "not_authorized"
