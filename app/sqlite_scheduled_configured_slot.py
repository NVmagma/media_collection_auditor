"""Configured settings + real GET collector + daily dispatch in marked labs only.

Not imported by the production audit entry point. SQLite activation remains
blocked there. Arr delivery requires the explicit disposable deliver_arr option.
"""
from datetime import datetime
from time import monotonic

from app.sqlite_arr_catalog import configured_arr_queue_resolver
from app.sqlite_jellyfin_collection import validated_tag_names
from app.sqlite_scheduled_jellyfin import (scheduled_inventory_signal_reader,
    scheduled_protection_provider)
from app.sqlite_scheduled_routed_slot import run_disposable_routed_slot
from app.sqlite_scheduled_settings import scheduled_worker_from_settings
from app.sqlite_scheduled_transport import ScheduledJellyfinGET


def run_configured_disposable_slot(*, root, settings, scheduled_at, now,
        clock=datetime.now, timer=monotonic, maximum_run_seconds=3600, deliver_arr=False):
    """Detach effective policy once, then freshly collect on scan and each move.

    DRY_RUN=false is mandatory for this disposable rename acceptance entry point;
    no production execution or implicit live selection is introduced. Transport
    request limits span all scans, rebuilds and move checks within this attempt.
    """
    if type(deliver_arr) is not bool:
        raise ValueError('Explicit disposable Arr delivery selection required')
    from app.sqlite_scheduled_arr_delivery import configured_arr_delivery
    values = dict(settings)
    config, scan, protect = _configured_run_inputs(settings=values, clock=clock)
    return run_disposable_routed_slot(root=root, config=config,
        scheduled_at=scheduled_at, now=now, fetch_signals=scan,
        fetch_protection=protect, clock=clock, timer=timer,
        maximum_run_seconds=maximum_run_seconds,
        resolve_arr_requests=configured_arr_queue_resolver(settings=values, config=config),
        complete_arr_requests=configured_arr_delivery(settings=values, config=config) if deliver_arr else None)


def _configured_run_inputs(*, settings, clock, allow_dry_run=False):
    """Shared detached settings and fresh collectors; construction performs no HTTP."""
    values = dict(settings)
    config = scheduled_worker_from_settings(values)
    if type(allow_dry_run) is not bool:
        raise ValueError('Explicit preview selection required')
    if not allow_dry_run and values.get('DRY_RUN', 'true').strip().lower() != 'false':
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

    return config, scan, protect
