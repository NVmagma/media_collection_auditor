"""Fail-closed, advisory recovery decision matrix for experimental SQLite.

This pure classifier never authorizes clearing, replaying, or deleting media.
Inputs must be allowlisted diagnostic statuses, not arbitrary service payloads.
"""

from __future__ import annotations

from typing import Any

FS = frozenset({"source_only", "destination_only_unverified", "both_present",
                "both_missing", "unavailable", "unsafe", "invalid"})
IDENTITY = frozenset({"consistent_not_authoritative", "incomplete", "mismatch"})
EVIDENCE = frozenset({"schema_valid_untrusted", "unverified"})
FINGERPRINT = frozenset({"metadata_consistent_unverified", "unverified"})
MOUNT = frozenset({"relative_paths_consistent_unverified", "unverified"})


def classify_move_recovery(
    *, filesystem: Any, identity: Any, evidence: Any,
    source_fingerprint: Any, destination_fingerprint: Any,
    mount_binding: Any, cross_device: Any = "unknown",
) -> dict[str, str]:
    """Classify observations without treating agreement as proof.

    Unknown or malformed values block evaluation rather than defaulting to
    an optimistic interpretation. No raw paths, IDs or credentials are emitted.
    """
    base = {"status": "blocked", "authorization": "not_authorized",
            "reconciliation": "disabled", "decision": "manual_review_required"}
    if (any(not isinstance(value, str) for value in (
            filesystem, identity, evidence, source_fingerprint,
            destination_fingerprint, mount_binding, cross_device))
            or filesystem not in FS or identity not in IDENTITY
            or evidence not in EVIDENCE
            or source_fingerprint not in FINGERPRINT
            or destination_fingerprint not in FINGERPRINT
            or mount_binding not in MOUNT
            or cross_device not in ("unknown", "same_device", "cross_device")):
        return {**base, "reason": "invalid_diagnostic_input"}
    if filesystem in ("unavailable", "unsafe", "invalid"):
        return {**base, "reason": "filesystem_not_trustworthy"}
    if filesystem == "both_present":
        return {**base, "reason": "duplicate_locations_ambiguous"}
    if filesystem == "both_missing":
        return {**base, "reason": "both_locations_missing"}
    if identity != "consistent_not_authoritative":
        return {**base, "reason": "service_identity_unverified"}
    if evidence != "schema_valid_untrusted":
        return {**base, "reason": "pre_move_evidence_unavailable"}
    if cross_device != "same_device":
        return {**base, "reason": "non_atomic_move_scope_unverified"}
    if mount_binding != "relative_paths_consistent_unverified":
        return {**base, "reason": "mount_namespace_unverified"}
    if filesystem == "source_only":
        return {**base, "reason": "source_still_present_no_replay"}
    if destination_fingerprint != "metadata_consistent_unverified":
        return {**base, "reason": "destination_identity_not_proven"}
    return {**base, "reason": "all_observations_advisory_not_proof"}
