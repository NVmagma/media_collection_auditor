"""Serialized revision-chained batches for a marked disposable library only.

No production routing, saved-plan resume, external-writer exclusion or deletion.
The cooperating runner lock covers the complete batch. Each completed result
must match exactly the expected lifecycle change before the next candidate.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import math
import os
from pathlib import Path
import secrets
from time import monotonic

from app.sqlite_arr_queue_plan import planned_arr_queue_entry
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_scheduled_disposable_executor import _execute_scheduled_move_locked
from app.sqlite_scheduled_plan import ScheduledPlan
from app.sqlite_title_identity import validate_title_folder
from app.state_store import GuardedSQLiteStateStore


def execute_scheduled_disposable_batch(*, root, database, plan, title_folders,
        fetch_protection, clock=datetime.now, timer=monotonic,
        maximum_protection_seconds=30, fault_at=None, arr_sync_requests=None):
    """Consume this process's complete plan once; stop on the first uncertainty.

    fault_at=(candidate_index, boundary) is disposable fault injection only.
    Reported completed entries passed exact post-operation state/revision checks.
    A stopped candidate may already have moved: never infer replay permission.
    """
    with isolated_runner_lock(root) as verify_binding:
        return _execute_scheduled_batch_locked(root=root, database=database, plan=plan,
            title_folders=title_folders, fetch_protection=fetch_protection, clock=clock,
            timer=timer, maximum_protection_seconds=maximum_protection_seconds,
            fault_at=fault_at, verify_binding=verify_binding, arr_sync_requests=arr_sync_requests)


def _execute_scheduled_batch_locked(*, root, database, plan, title_folders,
        fetch_protection, clock, timer, maximum_protection_seconds, fault_at, verify_binding, arr_sync_requests=None):
    """Internal integration used while a full scheduled slot retains the lock."""
    root, database = Path(root), Path(database)
    if database != root / 'state.db' or not isinstance(plan, ScheduledPlan):
        raise ValueError('Disposable database and scheduled plan required')
    if len(plan.libraries) != 1:
        raise ValueError('Disposable batch binds one library stage tree')
    if (not isinstance(title_folders, dict)
            or set(title_folders) != {move.media_key for move in plan.moves}):
        raise ValueError('Exact candidate folder bindings required')
    for move in plan.moves:
        folder = validate_title_folder(title_folders[move.media_key])
        if move.media_key not in (folder, 'TV/' + folder):
            raise ValueError('Candidate folder and tracking identity mismatch')
    if len(set(title_folders.values())) != len(title_folders):
        raise ValueError('Aliased candidate folders')
    if fault_at is not None and (not isinstance(fault_at, tuple) or len(fault_at) != 2
            or type(fault_at[0]) is not int or not 0 <= fault_at[0] < len(plan.moves)
            or fault_at[1] not in ('after_intent', 'after_rename', 'after_applied')):
        raise ValueError('Invalid batch fault boundary')
    requests = deepcopy({} if arr_sync_requests is None else arr_sync_requests)
    if not isinstance(requests, dict) or not set(requests).issubset(title_folders):
        raise ValueError('Only planned candidate Arr queue requests are accepted')
    queue_entries = {}
    stage_names = {'Holding': 'holding', 'Keep': 'keep', 'Removal': 'removal'}
    for move in plan.moves:
        if move.media_key in requests:
            queue_entries[move.media_key] = planned_arr_queue_entry(request=requests[move.media_key],
                media_key=move.media_key, title_folder=title_folders[move.media_key],
                destination_stage=stage_names[move.destination_stage])
    base = {'fixture_only': True, 'production_authorized': False,
            'production_activation': 'disabled', 'replay_allowed': False}
    completed = []
    def stopped(reason, index):
        return {**base, 'status': 'stopped', 'reason': reason,
                'completed': tuple(completed), 'stopped_index': index}
    store = GuardedSQLiteStateStore(database)
    expected, revision = store.load_with_revision()
    if plan.process_id != os.getpid():
        return stopped('plan_process_changed', None)
    if revision != plan.revision or expected.get(INTENTS_KEY):
        return stopped('stale_plan_or_pending_operation', None)
    chained = plan
    batch_id = secrets.token_hex(16)
    for index, move in enumerate(plan.moves):
        verify_binding()
        tick = timer()
        if not math.isfinite(tick) or not plan.created_tick <= tick < plan.deadline_tick:
            return stopped('plan_expired_or_clock_changed', index)
        current, current_revision = store.load_with_revision()
        if current_revision != revision or current != expected or current.get(INTENTS_KEY):
            return stopped('tracking_chain_changed', index)
        observed_at = clock()
        operation_id = batch_id + ':' + str(index)
        try:
            result = _execute_scheduled_move_locked(root=root, database=database,
                operation_id=operation_id, plan=chained, move=move,
                title_folder=title_folders[move.media_key], fetch_protection=fetch_protection,
                clock=lambda: observed_at, timer=timer,
                maximum_protection_seconds=maximum_protection_seconds,
                fault_at=fault_at[1] if fault_at and fault_at[0] == index else None,
                verify_binding=verify_binding, arr_sync_request=requests.get(move.media_key))
        except Exception:
            # No cleanup, intent clearance, retry or exception/credential dump.
            return stopped('move_failed_or_uncertain', index)
        expected_after = deepcopy(expected)
        if expected_after[CLOCKS[move.source_stage]].get(move.media_key) != move.source_clock:
            return stopped('planned_clock_binding_changed', index)
        expected_after[CLOCKS[move.source_stage]].pop(move.media_key)
        expected_after[CLOCKS[move.destination_stage]][move.media_key] = observed_at.isoformat()
        if move.media_key in queue_entries:
            expected_after['arr_sync_pending'][move.media_key] = queue_entries[move.media_key]
        verify_binding()
        after, after_revision = store.load_with_revision()
        if (result.get('status') != 'disposable_reconciled'
                or after_revision != revision + 3 or after != expected_after):
            return stopped('post_move_revision_or_state_changed', index)
        completed.append({'media_key': move.media_key, 'operation_id': operation_id,
                          'revision': after_revision})
        expected, revision = after, after_revision
        # Only advance after the exact guarded in-process result is observed.
        chained = replace(chained, revision=revision)
    return {**base, 'status': 'disposable_batch_complete', 'completed': tuple(completed),
            'final_revision': revision, 'capped_moves': plan.capped_moves}
