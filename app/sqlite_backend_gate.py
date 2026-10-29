"""Fail-closed production backend selection until SQLite activation is approved."""


def require_json_backend(value: str) -> None:
    """Reject unimplemented backend selections before audit side effects."""
    if value != "json":
        raise RuntimeError(
            "AUDITOR_STATE_BACKEND must be json; SQLite production activation is disabled"
        )


def preview_release_enabled() -> bool:
    """A separate immutable recipe bakes preview support; environment is ignored."""
    try:
        from app.sqlite_release_profile import PROFILE
    except ImportError:
        return False  # Legacy flat-module images remain JSON-only.
    return PROFILE == 'scheduled-preview-v1'


def live_release_enabled() -> bool:
    """Only an immutable live recipe can select the live binding validator."""
    try:
        from app.sqlite_release_profile import PROFILE
    except ImportError:
        return False
    return PROFILE == 'scheduled-live-moves-v1'


def require_sqlite_read_authority(*, settings=None):
    """Validate tracking access without granting permission to resume a move.

    A valid live database with a retained intent remains observable. Execution
    uses the stricter gate below and refuses that same pending operation.
    """
    return _require_sqlite_binding(settings=settings, for_execution=False)


def require_sqlite_production_activation(*, settings=None):
    """Require the compiled release profile and its matching execution binding."""
    return _require_sqlite_binding(settings=settings, for_execution=True)


def _require_sqlite_binding(*, settings, for_execution):
    if live_release_enabled():
        try:
            from app.sqlite_live_binding import validate_live_binding
            return validate_live_binding(settings=settings, for_execution=for_execution)
        except Exception:
            raise RuntimeError('SQLite live release binding unavailable') from None
    if not preview_release_enabled():
        require_json_backend('sqlite')
    try:
        from app.sqlite_preview_activation import validate_preview_activation
        return validate_preview_activation(settings=settings)
    except Exception:
        raise RuntimeError('SQLite production activation is disabled: preview release binding unavailable') from None
