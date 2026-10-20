"""Fail-closed production backend selection until SQLite activation is approved."""


def require_json_backend(value: str) -> None:
    """Reject unimplemented backend selections before audit side effects."""
    if value != "json":
        raise RuntimeError(
            "AUDITOR_STATE_BACKEND must be json; SQLite production activation is disabled"
        )
