"""Fail-closed production backend selection until SQLite activation is approved."""


def require_json_backend(value: str) -> None:
    """Reject unimplemented backend selections before audit side effects."""
    if value != "json":
        raise RuntimeError(
            "AUDITOR_STATE_BACKEND must be json; SQLite production activation is disabled"
        )


def require_sqlite_production_activation() -> None:
    """Release boundary: no environment value can authorize SQLite execution.

    Gate 8 may wire and test the candidate worker, but production remains sealed
    until release/rollback validation and explicit activation approval.
    """
    require_json_backend('sqlite')
