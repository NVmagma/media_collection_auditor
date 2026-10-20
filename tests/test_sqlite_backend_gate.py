"""Production audit entry point must never silently select experimental SQLite."""

import pytest

from app.sqlite_backend_gate import require_json_backend


def test_default_json_backend_is_allowed():
    assert require_json_backend("json") is None


@pytest.mark.parametrize("value", ["sqlite", "SQLite", "SQLITE", "", "auto", "json,sqlite"])
def test_unapproved_backends_fail_closed(value):
    with pytest.raises(RuntimeError, match="SQLite production activation is disabled"):
        require_json_backend(value)


@pytest.mark.parametrize("backend", ["sqlite", "auto", "SQLite", ""])
def test_real_audit_entrypoint_rejects_backend_before_side_effects(monkeypatch, backend):
    """Rejected backend must not create directories, lock, or start an audit."""
    import sys
    from pathlib import Path
    from unittest.mock import Mock

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "app"))
    import collection_auditor as auditor
    import sqlite_lock

    mkdir = Mock(side_effect=AssertionError("unexpected directory creation"))
    lock = Mock(side_effect=AssertionError("unexpected lock acquisition"))
    audit = Mock(side_effect=AssertionError("unexpected audit dispatch"))
    monkeypatch.setattr(auditor.os, "makedirs", mkdir)
    monkeypatch.setattr(sqlite_lock, "audit_run_lock", lock)
    monkeypatch.setattr(auditor, "_run_once_locked", audit)
    monkeypatch.setenv("AUDITOR_STATE_BACKEND", backend)

    with pytest.raises(RuntimeError, match="SQLite production activation is disabled"):
        auditor.run_once()
    mkdir.assert_not_called()
    lock.assert_not_called()
    audit.assert_not_called()
