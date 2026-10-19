"""Combined persisted evidence never authorizes or leaks sensitive data."""

import pytest

from app import sqlite_recovery_offline_evidence as module


def status(revision=5, operation_id="op-1"):
    return {"status": "blocked", "revision": revision,
            "operation_id": operation_id, "operation_kind": "move",
            "operation_phase": "intent_recorded"}


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
    result = module.inspect_offline_move_evidence("unused.db")
    assert result["evidence"]["source"] == "metadata_consistent_unverified"
    assert result["authorization"] == "not_authorized"
    assert result["reconciliation"] == "disabled"
    assert "never-display" not in str(result)
    assert "op-1" not in str(result)


@pytest.mark.parametrize("changed", ["revision", "operation", "fingerprint"])
def test_stale_or_changed_evidence_rejected(monkeypatch, changed):
    calls = iter([status(), status(6 if changed == "revision" else 5,
                                    "other" if changed == "operation" else "op-1")])
    monkeypatch.setattr(module, "inspect_pending_recovery_status", lambda _: next(calls))
    monkeypatch.setattr(module, "inspect_persisted_move_evidence",
                        lambda _: fingerprint(6 if changed == "fingerprint" else 5))
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
    with pytest.raises(RuntimeError, match="stale"):
        module.inspect_offline_move_evidence("unused.db")
