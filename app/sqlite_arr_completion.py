"""Known-outcome Arr completion in marked disposable labs only.

Owns the transport attempt and SQLite revision chain. This is not recovery:
pre-existing intents are refused, never adopted or replayed. Production is sealed.
"""
from contextlib import ExitStack
from copy import deepcopy
import os
from pathlib import Path
import stat

from app.sqlite_arr_queue_plan import planned_arr_queue_entry
from app.sqlite_arr_title_transport import ArrTitleUpdate
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_isolated_arr_runner import STAGES
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_operation_coordinator import INTENTS_KEY, SQLiteOperationCoordinator
from app.sqlite_scheduled_paths import _open_directory
from app.sqlite_title_identity import validate_title_folder
from app.state_store import GuardedSQLiteStateStore


def complete_disposable_arr_request(*, root, operation_id, media_key, title_folder,
        details, source_path, base_url, token):
    """One intent, one PUT, two GET readbacks, one exact queue/intent clearance.

    No generic verifier/receipt supplied by a caller can authorize clearance.
    Destination and all stage parents stay pinned while the controller owns its
    lock. Fresh remote requests each recheck the same state and local binding.
    Any exception propagates without retry or cleanup of uncertain state.
    """
    root = Path(root)
    folder = validate_title_folder(title_folder)
    request = deepcopy(details)
    # Strict shape/service/key validation happens before acquiring/creating lock.
    planned_arr_queue_entry(request=request, media_key=media_key,
        title_folder=folder, destination_stage='keep')
    with isolated_runner_lock(root) as verify_control, ExitStack() as stack:
        database = root / 'state.db'
        database_fd = os.open(database, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        stack.callback(os.close, database_fd)
        session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
        before, _ = session.read_verified_snapshot()
        if INTENTS_KEY in before:
            raise RuntimeError('Unresolved operation; Arr completion cannot replay')
        queued = before['arr_sync_pending'].get(media_key)
        if not isinstance(queued, dict) or queued.get('stage') not in STAGES:
            raise RuntimeError('Bound Arr queue required')
        stage = queued['stage']
        expected_queue = planned_arr_queue_entry(request=request, media_key=media_key,
            title_folder=folder, destination_stage=stage)
        if queued != expected_queue:
            raise RuntimeError('Exact Arr queue identity required')
        section = STAGES[stage]
        if media_key not in before[section] or any(media_key in before[other]
                for other in CLOCKS.values() if other != section):
            raise RuntimeError('Unique destination clock required')
        parents = {}
        for name in ('transient', 'holding', 'keep', 'removal'):
            fd = _open_directory(str(root / name))
            stack.callback(os.close, fd)
            parents[name] = fd
        title_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                           dir_fd=parents[stage])
        stack.callback(os.close, title_fd)

        def same_identity(info, held):
            return (info.st_dev, info.st_ino) == (held.st_dev, held.st_ino)

        def verify():
            verify_control()
            if not same_identity(database.stat(follow_symlinks=False), os.fstat(database_fd)):
                raise RuntimeError('Arr control database replaced')
            present = []
            for name, fd in parents.items():
                if not same_identity(os.stat(root / name, follow_symlinks=False), os.fstat(fd)):
                    raise RuntimeError('Arr stage root replaced')
                try:
                    info = os.stat(folder, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISDIR(info.st_mode):
                    raise RuntimeError('Unsafe Arr destination')
                present.append(name)
                if name == stage and not same_identity(info, os.fstat(title_fd)):
                    raise RuntimeError('Arr destination replaced')
            if present != [stage]:
                raise RuntimeError('Arr destination missing or ambiguous')
            session.read_verified_snapshot()

        transport = ArrTitleUpdate(service=request['service'], base_url=base_url, token=token,
            source_path=source_path, title_folder=folder, verify_binding=verify)
        verify()
        coordinator = SQLiteOperationCoordinator(session)
        coordinator.begin(operation_id, 'arr_sync', {**request, 'media_key': media_key,
            'title_folder': folder, 'stage': stage})
        intent = deepcopy(session.state[INTENTS_KEY])
        # The concrete transport returns only after known acknowledgement and two
        # independent exact readbacks. An exception never reaches clearance.
        transport(request)
        verify()
        if session.state[INTENTS_KEY] != intent:
            raise RuntimeError('Arr intent changed')
        coordinator.mark_applied(operation_id)
        verify()
        applied = deepcopy(intent)
        applied['phase'] = 'applied_pending_reconciliation'
        if session.state[INTENTS_KEY] != applied or session.state['arr_sync_pending'][media_key] != queued:
            raise RuntimeError('Arr applied intent or queue changed')
        # Queue and this exact intent disappear in one CAS. Clocks, unrelated
        # queues and unknown tracking fields are copied without modification.
        session.state['arr_sync_pending'].pop(media_key)
        session.state.pop(INTENTS_KEY)
        session.checkpoint()
        verify()
        return {'status': 'disposable_arr_completion_verified', 'revision': session.revision,
            'fixture_only': True, 'production_authorized': False,
            'production_activation': 'disabled', 'automatic_retry': False}
