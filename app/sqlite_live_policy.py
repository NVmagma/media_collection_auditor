"""Initial live-move policy contract; validation never activates a release.

A separately bound live image, mutable-state validation and disposable acceptance
are still required. The deployed preview gate is intentionally unchanged.
"""
from collections.abc import Mapping
from app.sqlite_scheduled_settings import scheduled_worker_from_settings

INITIAL_ACTION_LIMIT = 1
DISABLED = ('ALLOW_PERMANENT_DELETE', 'ALLOW_FILESYSTEM_DELETE',
            'ALLOW_CROSS_FILESYSTEM_MOVES', 'ENABLE_SEASON_PRUNING')


def validate_initial_live_policy(settings):
    """Return detached scheduled policy for a one-title initial live run.

    This function does no filesystem/network I/O and returns no authorization.
    Effective saved-config precedence must be resolved by the future live binding.
    """
    if not isinstance(settings, Mapping):
        raise ValueError('Effective live settings mapping required')
    values=dict(settings)
    required={'AUDITOR_STATE_BACKEND':'sqlite', 'DRY_RUN':'false',
              'READ_ONLY_API_SERVICE':'false', **{key:'false' for key in DISABLED}}
    for key,expected in required.items():
        value=values.get(key)
        if not isinstance(value,str) or value.strip().lower()!=expected:
            raise ValueError(key+': explicit initial live policy required')
    config=scheduled_worker_from_settings(values)
    if config.maximum_actions!=INITIAL_ACTION_LIMIT:
        raise ValueError('MAX_ACTIONS_PER_RUN: initial live run requires one title globally')
    return config
