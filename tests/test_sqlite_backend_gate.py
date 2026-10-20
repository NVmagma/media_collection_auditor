"""Production audit entry point must never silently select experimental SQLite."""

import pytest

from app.sqlite_backend_gate import require_json_backend


def test_default_json_backend_is_allowed():
    assert require_json_backend("json") is None


@pytest.mark.parametrize("value", ["sqlite", "SQLite", "SQLITE", "", "auto", "json,sqlite"])
def test_unapproved_backends_fail_closed(value):
    with pytest.raises(RuntimeError, match="SQLite production activation is disabled"):
        require_json_backend(value)
