"""Combined persisted evidence never authorizes or leaks sensitive data."""

import pytest

from app import sqlite_recovery_offline_evidence as module


def status(revision=5, operation_id="op-1"):
    return {"status": "blocked", "revision": revision,
            "operation_id": operation_id, "operation_kind": "move",
            "operation_phase": "intent_recorded"}


def filesystem(revision=5):
    return {"revision": revision, "status": "blocked",
            "authorization": "not_authorized", "interpretation": "both_present_ambiguous"}


def fingerprint(revision=5):
    return {"revision": revision, "status": "blocked",
            "authorization": "not_authorized",
            "evidence_verification": "schema_valid_untrusted",
            "evidence_reason": "provenance_not_verified",
            "source_fingerprint": "metadata_consistent_unverified",
            "source_reason": "matching_metadata_not_proof",
            "destination_fingerprint": "unverified",
            "destination_reason": "fingerprint_mismatch",
            "secret": "never-display"}


def test_combined_evidence_redacted_and_blocked(monkeypatch):
    monkeypatch.setattr(module, "inspect_pending_recovery_status", lambda _: status())
    monkeypatch.setattr(module, "inspect_persisted_move_evidence", lambda _: fingerprint())
    monkeypatch.setattr(module, "inspect_pending_move_filesystem", lambda _: filesystem())
    result = module.inspect_offline_move_evidence("unused.db")
    assert result["evidence"]["source"] == "metadata_consistent_unverified"
    assert result["authorization"] == "not_authorized"
    assert result["reconciliation"] == "disabled"
    assert result["decision"]["reason"] == "duplicate_locations_ambiguous"
    assert result["decision"]["authorization"] == "not_authorized"
    assert "never-display" not in str(result)
    assert "op-1" not in str(result)


@pytest.mark.parametrize("changed", ["revision", "operation", "fingerprint"])
def test_stale_or_changed_evidence_rejected(monkeypatch, changed):
    calls = iter([status(), status(6 if changed == "revision" else 5,
                                    "other" if changed == "operation" else "op-1")])
    monkeypatch.setattr(module, "inspect_pending_recovery_status", lambda _: next(calls))
    monkeypatch.setattr(module, "inspect_persisted_move_evidence",
                        lambda _: fingerprint(6 if changed == "fingerprint" else 5))
    monkeypatch.setattr(module, "inspect_pending_move_filesystem", lambda _: filesystem())
    with pytest.raises(RuntimeError, match="stale"):
        module.inspect_offline_move_evidence("unused.db")


def test_no_move_skips_filesystem_inspection(monkeypatch):
    monkeypatch.setattr(module, "inspect_pending_recovery_status",
                        lambda _: {"status": "no_pending_operation"})
    def forbidden(_):
        raise AssertionError("filesystem must not be inspected")
    monkeypatch.setattr(module, "inspect_persisted_move_evidence", forbidden)
    with pytest.raises(RuntimeError, match="Pending move unavailable"):
        module.inspect_offline_move_evidence("unused.db")


def test_invalid_fingerprint_report_never_becomes_clear(monkeypatch):
    monkeypatch.setattr(module, "inspect_pending_recovery_status", lambda _: status())
    monkeypatch.setattr(module, "inspect_persisted_move_evidence",
                        lambda _: dict(fingerprint(), authorization="authorized"))
    monkeypatch.setattr(module, "inspect_pending_move_filesystem", lambda _: filesystem())
    with pytest.raises(RuntimeError, match="stale"):
        module.inspect_offline_move_evidence("unused.db")


def test_filesystem_revision_race_is_rejected(monkeypatch):
    monkeypatch.setattr(module, "inspect_pending_recovery_status", lambda _: status())
    monkeypatch.setattr(module, "inspect_persisted_move_evidence", lambda _: fingerprint())
    monkeypatch.setattr(module, "inspect_pending_move_filesystem",
                        lambda _: filesystem(revision=6))
    with pytest.raises(RuntimeError, match="stale"):
        module.inspect_offline_move_evidence("unused.db")


def test_destination_only_still_lacks_independent_identity(monkeypatch):
    monkeypatch.setattr(module, "inspect_pending_recovery_status", lambda _: status())
    monkeypatch.setattr(module, "inspect_persisted_move_evidence", lambda _: fingerprint())
    monkeypatch.setattr(module, "inspect_pending_move_filesystem",
                        lambda _: dict(filesystem(), interpretation="destination_only_unverified"))
    result = module.inspect_offline_move_evidence("unused.db")
    assert result["decision"]["reason"] == "service_identity_unverified"
    assert result["decision"]["authorization"] == "not_authorized"


@pytest.mark.parametrize("failure", [
    RuntimeError("fingerprint unavailable"),
    OSError("filesystem inaccessible"),
])
def test_unavailable_inspector_never_produces_clearance(monkeypatch, failure):
    """An inspector error must propagate, never become a safe default."""
    monkeypatch.setattr(module, "inspect_pending_recovery_status", lambda _: status())
    monkeypatch.setattr(module, "inspect_persisted_move_evidence",
                        lambda _: (_ for _ in ()).throw(failure))
    monkeypatch.setattr(module, "inspect_pending_move_filesystem",
                        lambda _: pytest.fail("filesystem inspection must not run"))
    with pytest.raises(type(failure)):
        module.inspect_offline_move_evidence("unused.db")


@pytest.mark.parametrize("field,value", [
    ("status", "ready"),
    ("authorization", "authorized"),
    ("revision", 6),
])
def test_inconsistent_filesystem_report_rejected(monkeypatch, field, value):
    monkeypatch.setattr(module, "inspect_pending_recovery_status", lambda _: status())
    monkeypatch.setattr(module, "inspect_persisted_move_evidence", lambda _: fingerprint())
    monkeypatch.setattr(module, "inspect_pending_move_filesystem",
                        lambda _: dict(filesystem(), **{field: value}))
    with pytest.raises(RuntimeError, match="stale"):
        module.inspect_offline_move_evidence("unused.db")


@pytest.mark.parametrize("field,value", [
    ("status", "ready"),
    ("authorization", "authorized"),
    ("revision", 6),
])
def test_inconsistent_fingerprint_report_rejected(monkeypatch, field, value):
    monkeypatch.setattr(module, "inspect_pending_recovery_status", lambda _: status())
    monkeypatch.setattr(module, "inspect_persisted_move_evidence",
                        lambda _: dict(fingerprint(), **{field: value}))
    monkeypatch.setattr(module, "inspect_pending_move_filesystem", lambda _: filesystem())
    with pytest.raises(RuntimeError, match="stale"):
        module.inspect_offline_move_evidence("unused.db")
