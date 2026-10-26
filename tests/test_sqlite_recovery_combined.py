"""Combined recovery evidence must fail closed and avoid sensitive payloads."""

import pytest

from app import sqlite_recovery_combined as combined


def status(revision=4):
    return {
        "revision": revision, "status": "blocked",
        "operation_id": "op1", "operation_kind": "move",
    }


def filesystem(revision=4):
    return {
        "revision": revision, "source_status": "missing",
        "destination_status": "present",
        "interpretation": "destination_only_unverified",
    }


def service(revision=4):
    return {
        "revision": revision, "status": "blocked",
        "operation_id": "op1",
        "blocker": "reconciliation_not_authorized",
        "observation": {"token": "never-expose"},
        "jellyfin_protection": {"secret": "never-expose"},
    }


def test_combined_evidence_never_authorizes_or_exposes_service_data(monkeypatch):
    monkeypatch.setattr(combined, "inspect_pending_recovery_status", lambda _: status())
    monkeypatch.setattr(combined, "inspect_pending_move_filesystem", lambda _: filesystem())
    monkeypatch.setattr(combined, "inspect_http_recovery_report", lambda _, **kw: service())
    result = combined.inspect_combined_move_recovery("unused.db")
    assert result["authorization"] == "not_authorized"
    assert result["external_verification"] == "incomplete"
    assert result["reconciliation"] == "disabled"
    assert result["filesystem"]["interpretation"] == "destination_only_unverified"
    assert "never-expose" not in str(result)


@pytest.mark.parametrize("changed", ["filesystem", "service", "final"])
def test_revision_change_fails_closed(monkeypatch, changed):
    calls = iter([status(), status(5) if changed == "final" else status()])
    monkeypatch.setattr(combined, "inspect_pending_recovery_status", lambda _: next(calls))
    monkeypatch.setattr(combined, "inspect_pending_move_filesystem",
                        lambda _: filesystem(5 if changed == "filesystem" else 4))
    monkeypatch.setattr(combined, "inspect_http_recovery_report",
                        lambda _, **kw: service(5 if changed == "service" else 4))
    with pytest.raises(RuntimeError, match="stale"):
        combined.inspect_combined_move_recovery("unused.db")


def test_no_move_never_attempts_external_reads(monkeypatch):
    monkeypatch.setattr(combined, "inspect_pending_recovery_status",
                        lambda _: {"status": "no_pending_operation"})
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected external read")
    monkeypatch.setattr(combined, "inspect_pending_move_filesystem", forbidden)
    monkeypatch.setattr(combined, "inspect_http_recovery_report", forbidden)
    with pytest.raises(RuntimeError, match="Pending move unavailable"):
        combined.inspect_combined_move_recovery("unused.db")
