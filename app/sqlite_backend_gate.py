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


def require_sqlite_production_activation(*, settings=None):
    """Sealed by default; the preview image requires its prepared-state binding.

    This returns a detached effective settings mapping only for validated preview
    execution. It never allows moves, Arr writes, clock checkpoints or deletion.
    """
    if not preview_release_enabled():
        require_json_backend('sqlite')
    try:
        from app.sqlite_preview_activation import validate_preview_activation
        return validate_preview_activation(settings=settings)
    except Exception:
        raise RuntimeError('SQLite production activation is disabled: preview release binding unavailable') from None
