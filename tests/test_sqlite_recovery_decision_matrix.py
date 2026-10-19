"""Recovery decision matrix must never grant reconciliation."""

import itertools

import pytest

from app.sqlite_recovery_decision_matrix import classify_move_recovery


def case(**changes):
    values = {
        "filesystem": "destination_only_unverified",
        "identity": "consistent_not_authoritative",
        "evidence": "schema_valid_untrusted",
        "source_fingerprint": "unverified",
        "destination_fingerprint": "metadata_consistent_unverified",
        "mount_binding": "relative_paths_consistent_unverified",
        "cross_device": "same_device",
    }
    values.update(changes)
    return classify_move_recovery(**values)


def test_all_agreeing_evidence_is_still_blocked():
    result = case()
    assert result["reason"] == "all_observations_advisory_not_proof"
    assert result["authorization"] == "not_authorized"
    assert result["reconciliation"] == "disabled"


@pytest.mark.parametrize("filesystem,reason", [
    ("both_present", "duplicate_locations_ambiguous"),
    ("both_missing", "both_locations_missing"),
    ("unsafe", "filesystem_not_trustworthy"),
    ("unavailable", "filesystem_not_trustworthy"),
    ("source_only", "source_still_present_no_replay"),
])
def test_filesystem_scenarios_block(filesystem, reason):
    assert case(filesystem=filesystem)["reason"] == reason


@pytest.mark.parametrize("changes,reason", [
    ({"identity": "mismatch"}, "service_identity_unverified"),
    ({"identity": "incomplete"}, "service_identity_unverified"),
    ({"evidence": "unverified"}, "pre_move_evidence_unavailable"),
    ({"cross_device": "cross_device"}, "non_atomic_move_scope_unverified"),
    ({"cross_device": "unknown"}, "non_atomic_move_scope_unverified"),
    ({"mount_binding": "unverified"}, "mount_namespace_unverified"),
    ({"destination_fingerprint": "unverified"}, "destination_identity_not_proven"),
])
def test_missing_independent_evidence_blocks(changes, reason):
    assert case(**changes)["reason"] == reason


@pytest.mark.parametrize("changes", [
    {"filesystem": "destination_present"},
    {"identity": {"secret": "token"}},
    {"evidence": None},
    {"source_fingerprint": "verified"},
    {"destination_fingerprint": "verified"},
    {"mount_binding": "verified"},
    {"cross_device": True},
])
def test_invalid_or_optimistic_statuses_rejected(changes):
    result = case(**changes)
    assert result["reason"] == "invalid_diagnostic_input"
    assert "token" not in str(result)
    assert result["authorization"] == "not_authorized"


def test_all_declared_scenarios_never_authorize():
    for fs, cross in itertools.product(
        ("source_only", "destination_only_unverified", "both_present", "both_missing"),
        ("unknown", "same_device", "cross_device"),
    ):
        result = case(filesystem=fs, cross_device=cross)
        assert result["status"] == "blocked"
        assert result["authorization"] == "not_authorized"
        assert result["reconciliation"] == "disabled"
