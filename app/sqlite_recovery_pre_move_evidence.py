"""Versioned advisory pre-move evidence envelope for offline SQLite experiments.

The envelope is a candidate record, not a trusted provenance chain. Persisting
it does not authorize an operation or prove which object was later moved.
"""

from __future__ import annotations

from typing import Any

from app.sqlite_recovery_fingerprint import capture_directory_fingerprint

VERSION = 1
FIELDS = ("device", "inode", "mode", "mtime_ns", "ctime_ns")


def validate_pre_move_evidence(value: Any) -> dict[str, str]:
    """Validate a strict schema without exposing paths or filesystem identifiers."""
    blocked = {"status": "blocked", "authorization": "not_authorized",
               "evidence_verification": "unverified"}
    if not isinstance(value, dict) or set(value) != {"version", "source", "fingerprint"}:
        return {**blocked, "reason": "invalid_evidence_envelope"}
    if type(value["version"]) is not int or value["version"] != VERSION:
        return {**blocked, "reason": "unsupported_evidence_version"}
    source = value["source"]
    if source != "pre_move_metadata":
        return {**blocked, "reason": "invalid_evidence_source"}
    fingerprint = value["fingerprint"]
    if (not isinstance(fingerprint, dict)
            or set(fingerprint) != {"status", *FIELDS}
            or fingerprint.get("status") != "captured"
            or any(type(fingerprint[field]) is not int or fingerprint[field] < 0
                   for field in FIELDS)):
        return {**blocked, "reason": "invalid_fingerprint"}
    return {**blocked, "evidence_verification": "schema_valid_untrusted",
            "reason": "provenance_not_verified"}


def build_pre_move_evidence(path: Any) -> dict[str, Any]:
    """Capture a candidate envelope, refusing incomplete filesystem reads.

    Caller must arrange durable intent ordering separately; this function
    never changes a database or performs an external media operation.
    """
    fingerprint = capture_directory_fingerprint(path)
    if fingerprint.get("status") != "captured":
        raise RuntimeError("Pre-move filesystem evidence unavailable")
    envelope = {"version": VERSION, "source": "pre_move_metadata",
                "fingerprint": fingerprint}
    if validate_pre_move_evidence(envelope)["evidence_verification"] != "schema_valid_untrusted":
        raise RuntimeError("Pre-move filesystem evidence invalid")
    return envelope
