"""Configured settings + real GET collector + daily dispatch in marked labs only.

Not imported by the production audit entry point. SQLite activation remains
blocked there. This integration creates no Arr clients and delivers no mutations.
"""
from datetime import datetime
from time import monotonic

from app.sqlite_jellyfin_collection import validated_tag_names
from app.sqlite_scheduled_jellyfin import (scheduled_inventory_signal_reader,
    scheduled_protection_provider)
from app.sqlite_scheduled_routed_slot import run_disposable_routed_slot
from app.sqlite_scheduled_settings import scheduled_worker_from_settings
from app.sqlite_scheduled_transport import ScheduledJellyfinGET


def run_configured_disposable_slot(*, root, settings, scheduled_at, now,
        clock=datetime.now, timer=monotonic, maximum_run_seconds=3600):
    """Detach effective policy once, then freshly collect on scan and each move.

    DRY_RUN=false is mandatory for this disposable rename acceptance entry point;
    no production execution or implicit live selection is introduced. Transport
    request limits span all scans, rebuilds and move checks within this attempt.
    """
    config = scheduled_worker_from_settings(settings)
    values = dict(settings)
    if values.get('DRY_RUN', 'true').strip().lower() != 'false':
        raise ValueError('Disposable rename acceptance requires explicit DRY_RUN=false')
    tags = validated_tag_names({field: values.get(key, default) for field, key, default in (
        ('keep', 'KEEP_TAG', 'keep'), ('disliked', 'DISLIKE_TAG', 'not-at-all'),
        ('protected', 'PROTECT_TAG', 'keep-forever'),
        ('keep_all', 'KEEP_ALL_SEASONS_TAG', 'keep-all-seasons'))})
    fetch = ScheduledJellyfinGET(base_url=values.get('JELLYFIN_HOST_URL'),
                               token=values.get('JELLYFIN_API_TOKEN'))
    reader = scheduled_inventory_signal_reader(fetch=fetch, clock=clock, tag_names=tags)
    bindings = {}

    def scan(binding):
        identity = (binding.folder, binding.jellyfin_type)
        if binding.media_key in bindings and bindings[binding.media_key] != identity:
            raise RuntimeError('Configured title binding changed during collection')
        bindings[binding.media_key] = identity
        return reader(binding)

    def protect(move):
        # Construction binds to this attempt's observed identities, while the
        # provider itself always makes new requests instead of reusing signals.
        return scheduled_protection_provider(fetch=fetch, bindings=bindings,
            clock=clock, tag_names=tags)(move)

    return run_disposable_routed_slot(root=root, config=config,
        scheduled_at=scheduled_at, now=now, fetch_signals=scan,
        fetch_protection=protect, clock=clock, timer=timer,
        maximum_run_seconds=maximum_run_seconds)
