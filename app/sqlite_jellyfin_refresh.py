"""Compatibility wrapper for the retained scheduled worker."""
from app.jellyfin_refresh import refresh_after_moves


def refresh_after_completed_live_run(*, settings, result, maximum_seconds=10):
    completed=(result.get('status') == 'disposable_scheduled_routed_slot_complete'
               and bool(result.get('completed')))
    return refresh_after_moves(settings=settings,completed=completed,maximum_seconds=maximum_seconds)
