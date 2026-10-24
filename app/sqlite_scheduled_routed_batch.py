"""Actual configured movie/TV renames with one DB, in marked disposable labs.

No production backend selection, copy/delete fallback, season pruning, Arr
network delivery, saved-plan adoption or restart replay. Existing disposable
single-tree executors keep their markers and contracts unchanged.
"""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import math
import os
from pathlib import Path
import secrets
import stat
from time import monotonic

from app.sqlite_arr_queue_plan import planned_arr_queue_entry
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_noreplace_rename import rename_directory_noreplace_at
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_rename_mount_binding import capture_rename_mount_binding, assert_rename_mount_binding
from app.sqlite_scheduled_content import observe_scheduled_content
from app.sqlite_scheduled_paths import _open_directory
from app.sqlite_scheduled_recheck import recheck_scheduled_move
from app.sqlite_scheduled_worker import ScheduledWorkerConfig, ScheduledWorkerPreparation
from app.state_store import GuardedSQLiteStateStore

_STAGE_NAMES = {'Waiting': 'transient', 'Holding': 'holding', 'Keep': 'keep', 'Removal': 'removal'}
_TRANSITIONS = {('Waiting', 'Holding'), ('Waiting', 'Keep'), ('Holding', 'Keep'), ('Holding', 'Removal')}


def _identity(info):
    return info.st_dev, info.st_ino


def execute_disposable_routed_batch(*, root, config, preparation, fetch_protection,
        arr_sync_requests=None, clock=datetime.now, timer=monotonic, maximum_protection_seconds=30):
    """Revalidate an ephemeral worker plan and route each title to its library.

    The cap was applied after the complete multi-library scan. Clock checkpoints
    must already be verified; this API never updates discovery clocks itself.
    Stop on the first failed/uncertain candidate, preserving earlier completions.
    """
    with isolated_runner_lock(root) as verify_binding:
        return _execute_routed_batch_locked(root=root, config=config, preparation=preparation,
            fetch_protection=fetch_protection, arr_sync_requests=arr_sync_requests,
            clock=clock, timer=timer, maximum_protection_seconds=maximum_protection_seconds,
            verify_binding=verify_binding)


def _execute_routed_batch_locked(*, root, config, preparation, fetch_protection,
        arr_sync_requests, clock, timer, maximum_protection_seconds, verify_binding):
    """Internal composition while the daily claim retains the runner lock."""
    root = Path(root)
    if (not isinstance(config, ScheduledWorkerConfig) or not isinstance(preparation, ScheduledWorkerPreparation)
            or preparation.configuration != config
            or preparation.clock_proposal is None or preparation.clock_proposal.changes
            or not callable(fetch_protection)):
        raise ValueError('Configured, fully checkpointed worker preparation required')
    plan = preparation.plan
    libraries = {library.name: library for library in config.libraries}
    if tuple(libraries) != plan.libraries or len(plan.moves) > config.maximum_actions:
        raise ValueError('Configured library/action-cap binding mismatch')
    roots = {(library.name, stage): path for library in config.libraries for stage, path in library.roots}
    captured_roots = {(name, stage): (path, identity) for name, stage, path, identity in preparation.root_bindings}
    if (set(roots) != set(captured_roots) or any(captured_roots[key][0] != path
            or root not in Path(path).parents for key, path in roots.items())):
        raise ValueError('Configured stage paths differ from the marked lab preparation')
    bindings = {binding.media_key: binding for binding in preparation.bindings}
    identities = dict(preparation.title_identities)
    requests = deepcopy({} if arr_sync_requests is None else arr_sync_requests)
    keys = {move.media_key for move in plan.moves}
    if not isinstance(requests, dict) or not set(requests).issubset(keys):
        raise ValueError('Only planned title Arr requests accepted')
    queue_entries = {}
    for move in plan.moves:
        binding = bindings.get(move.media_key)
        if (binding is None or move.media_key not in identities or binding.library != move.library
                or binding.stage != move.source_stage or (move.source_stage, move.destination_stage) not in _TRANSITIONS
                or libraries[move.library].media_key(binding.folder) != move.media_key):
            raise ValueError('Move and configured title identity mismatch')
        if move.media_key in requests:
            queue_entries[move.media_key] = planned_arr_queue_entry(request=requests[move.media_key],
                media_key=move.media_key, title_folder=binding.folder,
                destination_stage=_STAGE_NAMES[move.destination_stage])
    base = {'fixture_only': True, 'production_authorized': False, 'production_activation': 'disabled',
            'replay_allowed': False}
    completed = []
    def stopped(reason, index):
        return {**base, 'status': 'stopped', 'reason': reason,
                'completed': tuple(completed), 'stopped_index': index}
    store = GuardedSQLiteStateStore(root / 'state.db')
    expected, revision = store.load_with_revision()
    if (plan.process_id != os.getpid() or revision != plan.revision or INTENTS_KEY in expected
            or expected != preparation.clock_proposal.source_snapshot
            or preparation.clock_proposal.source_revision != revision):
        return stopped('stale_preparation_or_pending_operation', None)
    batch_id = secrets.token_hex(16)
    chained = plan
    for index, move in enumerate(plan.moves):
        try:
            verify_binding()
            current, current_revision = store.load_with_revision()
            if current != expected or current_revision != revision:
                raise RuntimeError('Tracking chain changed')
            observed_at = clock()
            operation_id = batch_id + ':' + str(index)
            binding = bindings[move.media_key]
            _move(root=root, store=store, library=libraries[move.library], roots=roots,
                captured_roots=captured_roots, title_identity=identities[move.media_key],
                folder=binding.folder, plan=chained, move=move, expected=expected,
                operation_id=operation_id, observed_at=observed_at,
                fetch_protection=fetch_protection, verify_binding=verify_binding,
                timer=timer, maximum_protection_seconds=maximum_protection_seconds,
                arr_request=requests.get(move.media_key), queue_entry=queue_entries.get(move.media_key))
            expected_after = deepcopy(expected)
            expected_after[CLOCKS[move.source_stage]].pop(move.media_key)
            expected_after[CLOCKS[move.destination_stage]][move.media_key] = observed_at.isoformat()
            if move.media_key in queue_entries:
                expected_after['arr_sync_pending'][move.media_key] = queue_entries[move.media_key]
            verify_binding()
            after, after_revision = store.load_with_revision()
            if after != expected_after or after_revision != revision + 3:
                raise RuntimeError('Post-move tracking chain changed')
        except Exception:
            return stopped('move_failed_or_uncertain', index)
        completed.append({'media_key': move.media_key, 'library': move.library,
                          'operation_id': operation_id, 'revision': after_revision})
        expected, revision = after, after_revision
        chained = replace(chained, revision=revision)
    return {**base, 'status': 'disposable_routed_batch_complete', 'completed': tuple(completed),
            'final_revision': revision, 'capped_moves': plan.capped_moves}


def _move(*, root, store, library, roots, captured_roots, title_identity, folder, plan, move,
        expected, operation_id, observed_at, fetch_protection, verify_binding,
        timer, maximum_protection_seconds, arr_request, queue_entry):
    if (not isinstance(observed_at, datetime) or observed_at.tzinfo is not None
            or observed_at > datetime.now() or observed_at < datetime.fromisoformat(move.source_clock)):
        raise RuntimeError('Invalid lifecycle observation time')
    with ExitStack() as stack:
        handles = {}
        # Pin every library root, not just this candidate's two endpoints.
        for key, path in roots.items():
            fd = _open_directory(path); stack.callback(os.close, fd); handles[key] = fd
            if _identity(os.fstat(fd)) != captured_roots[key][1]:
                raise RuntimeError('Configured stage root changed')
        source_key, destination_key = (move.library, move.source_stage), (move.library, move.destination_stage)
        source_path = roots[source_key] + '/' + folder
        destination_path = roots[destination_key] + '/' + folder
        source_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                            dir_fd=handles[source_key])
        stack.callback(os.close, source_fd)
        if _identity(os.fstat(source_fd)) != title_identity:
            raise RuntimeError('Planned source title changed')
        mount = capture_rename_mount_binding(handles[source_key], handles[destination_key], source_fd)
        def verify_paths(applied=False):
            verify_binding()
            for key, path in roots.items():
                fd = _open_directory(path)
                try:
                    if _identity(os.fstat(fd)) != captured_roots[key][1]:
                        raise RuntimeError('Configured stage root changed')
                finally: os.close(fd)
            for stage, _ in library.roots:
                try: info = os.stat(folder, dir_fd=handles[move.library, stage], follow_symlinks=False)
                except FileNotFoundError:
                    if stage == (move.destination_stage if applied else move.source_stage):
                        raise RuntimeError('Expected title location disappeared') from None
                    continue
                if (stage != (move.destination_stage if applied else move.source_stage)
                        or not stat.S_ISDIR(info.st_mode) or _identity(info) != title_identity):
                    raise RuntimeError('Title location ambiguous or replaced')
            assert_rename_mount_binding(mount, handles[source_key], handles[destination_key], source_fd)
        verify_paths()
        def read_tracking():
            verify_binding()
            return store.load_with_revision()
        report = recheck_scheduled_move(plan=plan, move=move, read_tracking=read_tracking,
            fetch_protection=fetch_protection, clock=lambda: observed_at, timer=timer,
            maximum_protection_seconds=maximum_protection_seconds)
        if report['status'] != 'revalidated_advisory':
            raise RuntimeError('Fresh decision unavailable or changed')
        if library.new_content_resets_clock and move.source_stage == 'Waiting':
            newest = observe_scheduled_content(title_path=source_path, now=observed_at,
                maximum_seconds=maximum_protection_seconds, timer=timer)
            if newest is not None and newest > datetime.fromisoformat(move.source_clock):
                raise RuntimeError('TV content changed after planning')
        def verify_deadline():
            tick = timer()
            if (not math.isfinite(tick) or not report['checked_tick'] <= tick < min(
                    plan.deadline_tick, report['protection_deadline_tick'])):
                raise RuntimeError('Fresh protection or plan expired')
        verify_paths(); verify_deadline()
        session = RevisionedAuditSession(store)
        before, revision = session.read_verified_snapshot()
        if revision != plan.revision or before != expected:
            raise RuntimeError('Source tracking changed')
        if move.media_key in before['arr_sync_pending']:
            raise RuntimeError('Existing Arr queue entry')
        details = {'media_key': move.media_key, 'source': source_path, 'destination': destination_path,
            'lifecycle_clock_binding': {'source_stage': _STAGE_NAMES[move.source_stage],
                'destination_stage': _STAGE_NAMES[move.destination_stage],
                'source_timestamp': move.source_clock, 'observed_at': observed_at.isoformat()},
            'rename_mount_binding': mount}
        if arr_request is not None: details['arr_sync_request'] = arr_request
        coordinator = SQLiteOperationCoordinator(session)
        coordinator.begin_move_with_evidence(operation_id, details)
        intent_snapshot, intent_revision = session.read_verified_snapshot()
        if intent_revision != revision + 1:
            raise RuntimeError('Intent revision mismatch')
        verify_paths(); verify_deadline()
        session.read_verified_snapshot()
        rename_directory_noreplace_at(handles[source_key], folder, handles[destination_key], folder)
        verify_paths(applied=True)
        os.fsync(handles[source_key]); os.fsync(handles[destination_key])
        coordinator.mark_applied(operation_id)
        verify_paths(applied=True)
        applied, applied_revision = session.read_verified_snapshot()
        expected_applied = deepcopy(intent_snapshot)
        expected_applied[INTENTS_KEY]['phase'] = 'applied_pending_reconciliation'
        if applied != expected_applied or applied_revision != revision + 2:
            raise RuntimeError('Applied state binding changed')
        final = deepcopy(before)
        final[CLOCKS[move.source_stage]].pop(move.media_key)
        final[CLOCKS[move.destination_stage]][move.media_key] = observed_at.isoformat()
        if queue_entry is not None: final['arr_sync_pending'][move.media_key] = queue_entry
        # Held source FD still witnesses the uniquely occupied destination.
        verify_paths(applied=True)
        session.read_verified_snapshot()
        session.state = final
        session.checkpoint()
        verify_paths(applied=True)
