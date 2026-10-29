"""One claimed daily slot: full scan, guarded clocks, fresh rebuild, routed moves.

Marked disposable roots only. No production worker selection, sleeps, catch-up,
claim deletion or automatic replay. Configured Arr delivery is explicitly composed. The claim retains one
cooperating runner lock across the whole operation; it does not fence media writers.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import math
from time import monotonic

from app.sqlite_arr_queue_plan import planned_arr_queue_entry
from app.sqlite_scheduled_clock_checkpoint import (_validate_clock_preparation,
    _prepare_configured_worker_locked)
from app.sqlite_scheduled_routed_batch import _execute_configured_batch_locked
from app.sqlite_scheduled_slot import claim_disposable_scheduled_slot


def run_disposable_routed_slot(*, root, config, scheduled_at, now, fetch_signals,
        fetch_protection, arr_sync_requests=None, clock=datetime.now, timer=monotonic,
        maximum_titles=100000, maximum_run_seconds=3600, maximum_protection_seconds=30,
        resolve_arr_requests=None, complete_arr_requests=None):
    """Attempt one due slot once; any failure leaves its claim in place.

    All-library collection and any clock checkpoint precede all moves. Requests
    are detached before callbacks, bound to observed titles, and filtered by the
    one globally capped plan. No clock/operation uncertainty is retried.
    """
    root = _validate_clock_preparation(root=root, config=config, fetch_signals=fetch_signals,
        clock=clock, timer=timer, maximum_scan_seconds=maximum_run_seconds)
    _validate_routed_limits(fetch_protection, maximum_titles, maximum_protection_seconds)
    started = timer()
    with claim_disposable_scheduled_slot(root=root, schedule=config.schedule,
            scheduled_at=scheduled_at, now=now) as verify_claim:
        return _run_routed_slot_locked(database=root / 'state.db', config=config,
            scheduled_at=scheduled_at, fetch_signals=fetch_signals,
            fetch_protection=fetch_protection, arr_sync_requests=arr_sync_requests,
            clock=clock, timer=timer, maximum_titles=maximum_titles,
            maximum_run_seconds=maximum_run_seconds,
            maximum_protection_seconds=maximum_protection_seconds, verify_claim=verify_claim,
            started_tick=started, resolve_arr_requests=resolve_arr_requests,
            complete_arr_requests=complete_arr_requests)


def _run_routed_slot_locked(*, database, config, scheduled_at, fetch_signals,
        fetch_protection, arr_sync_requests, clock, timer, maximum_titles,
        maximum_run_seconds, maximum_protection_seconds, verify_claim, started_tick=None,
        resolve_arr_requests=None, complete_arr_requests=None, record_details=None):
    """Shared attempt body after a caller has durably claimed its bound control slot."""
    _validate_routed_limits(fetch_protection, maximum_titles, maximum_protection_seconds)
    if resolve_arr_requests is not None and (not callable(resolve_arr_requests) or arr_sync_requests is not None):
        raise ValueError('One explicit Arr request source required')
    if complete_arr_requests is not None and not callable(complete_arr_requests):
        raise ValueError('Callable Arr completion required')
    requests = deepcopy({} if arr_sync_requests is None else arr_sync_requests)
    if not isinstance(requests, dict):
        raise ValueError('Explicit Arr request mapping required')
    started = timer() if started_tick is None else started_tick
    def remaining():
        elapsed = timer() - started
        if not math.isfinite(elapsed) or not 0 <= elapsed < maximum_run_seconds:
            raise RuntimeError('Scheduled run deadline exceeded')
        return maximum_run_seconds - elapsed
    checkpoint = _prepare_configured_worker_locked(database=database, config=config,
        fetch_signals=fetch_signals, clock=clock, timer=timer, maximum_titles=maximum_titles,
        maximum_scan_seconds=remaining(), verify_binding=verify_claim)
    verify_claim(); remaining()
    prepared = checkpoint.preparation
    if resolve_arr_requests is not None:
        requests = deepcopy(resolve_arr_requests(prepared))
        verify_claim(); remaining()
        if not isinstance(requests, dict):
            raise ValueError('Explicit resolved Arr mapping required')
    bindings = {binding.media_key: binding for binding in prepared.bindings}
    if not set(requests).issubset(bindings):
        raise ValueError('Arr request is not bound to an observed title')
    # Validate all supplied identities, including titles excluded by the cap.
    for key, request in requests.items():
        planned_arr_queue_entry(request=request, media_key=key,
            title_folder=bindings[key].folder, destination_stage='holding')
    keys = {move.media_key for move in prepared.plan.moves}
    prepared = replace(prepared, plan=replace(prepared.plan,
        deadline_tick=min(prepared.plan.deadline_tick, started + maximum_run_seconds)))
    def complete(**kwargs):
        verify_claim(); remaining()
        return complete_arr_requests(database=database, verify_binding=verify_claim,
            remaining=remaining, deadline_tick=started + maximum_run_seconds, **kwargs)
    result = _execute_configured_batch_locked(database=database, config=config, preparation=prepared,
        fetch_protection=fetch_protection,
        arr_sync_requests={key: value for key, value in requests.items() if key in keys},
        clock=clock, timer=timer, maximum_protection_seconds=maximum_protection_seconds,
        verify_binding=verify_claim,
        complete_arr_requests=complete if complete_arr_requests is not None else None, record_details=record_details)
    verify_claim(); remaining()
    return {**result, 'status': ('disposable_scheduled_routed_slot_complete'
        if result['status'] == 'disposable_routed_batch_complete' else result['status']),
        'scheduled_at': scheduled_at.astimezone(timezone.utc).isoformat(),
        'clock_checkpointed': checkpoint.checkpointed,
        'initial_revision': checkpoint.initial_revision,
        'post_clock_revision': checkpoint.final_revision}


def _validate_routed_limits(fetch_protection, maximum_titles, maximum_protection_seconds):
    if (not callable(fetch_protection) or type(maximum_titles) is not int
            or not 1 <= maximum_titles <= 100000
            or type(maximum_protection_seconds) not in (int, float)
            or not math.isfinite(maximum_protection_seconds) or maximum_protection_seconds <= 0):
        raise ValueError('Bounded collection and protection policy required')
