"""Scheduled-plan rename integration for marked disposable media ONLY.

Uses the existing no-overwrite, held-directory, live-witness SQLite flow. There
is no production path, deletion, copy fallback, Arr request or restart replay.
External writers are not excluded; source-entry substitution remains a race and
post-rename identity checks can detect uncertainty rather than undo a rename.
"""
from datetime import datetime
import math
from pathlib import Path
from time import monotonic

from app.sqlite_disposable_lifecycle_flow import execute_disposable_lifecycle_move
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_scheduled_recheck import recheck_scheduled_move
from app.sqlite_title_identity import validate_title_folder
from app.state_store import GuardedSQLiteStateStore

_STAGES = {'Waiting': 'transient', 'Holding': 'holding', 'Keep': 'keep', 'Removal': 'removal'}


def execute_scheduled_disposable_move(*, root, database, operation_id, plan, move,
        title_folder, fetch_protection, clock=datetime.now, timer=monotonic,
        maximum_protection_seconds=30, fault_at=None):
    """Run one scheduled candidate; any post-intent failure remains pending.

    Each successful move changes the revision. This API intentionally rejects
    the unchanged old plan on a second call; batch revision chaining is not yet
    implemented. All roots must carry the existing disposable-only marker.
    """
    root, database = Path(root), Path(database)
    if database != root / 'state.db':
        raise RuntimeError('Disposable database binding mismatch')
    validate_title_folder(title_folder)
    if move.media_key not in (title_folder, 'TV/' + title_folder):
        raise RuntimeError('Title identity and folder mismatch')
    with isolated_runner_lock(root) as verify_binding:
        store = GuardedSQLiteStateStore(database)
        def read_tracking():
            verify_binding()
            return store.load_with_revision()
        fresh = None
        def before_intent():
            nonlocal fresh
            report = recheck_scheduled_move(plan=plan, move=move, read_tracking=read_tracking,
                fetch_protection=fetch_protection, clock=clock, timer=timer,
                maximum_protection_seconds=maximum_protection_seconds)
            if report['status'] != 'revalidated_advisory':
                raise RuntimeError('Scheduled move blocked: ' + report['reason'])
            fresh = report
        def before_rename():
            # Hashing/persisting evidence must not let a once-fresh check age out.
            tick = timer()
            if (fresh is None or not math.isfinite(tick)
                    or not fresh['checked_tick'] <= tick < min(
                        plan.deadline_tick, fresh['protection_deadline_tick'])):
                raise RuntimeError('Protection or plan expired after intent; retained')
            state, revision = read_tracking()
            pending = state.get(INTENTS_KEY)
            if (revision != plan.revision + 1 or not isinstance(pending, dict)
                    or pending.get('id') != operation_id or pending.get('kind') != 'move'
                    or pending.get('phase') != 'intent_recorded'):
                raise RuntimeError('Intent changed before rename; retained')
            tick = timer()
            if (not math.isfinite(tick) or not fresh['checked_tick'] <= tick < min(
                    plan.deadline_tick, fresh['protection_deadline_tick'])):
                raise RuntimeError('Protection or plan expired during intent review; retained')
        result = execute_disposable_lifecycle_move(root=root, database=database,
            operation_id=operation_id, media_key=move.media_key, title_folder=title_folder,
            source_stage=_STAGES[move.source_stage], destination_stage=_STAGES[move.destination_stage],
            expected_revision=plan.revision, observed_at=clock(), fault_at=fault_at,
            _use_directory_handles=True, _verify_runner_binding=verify_binding,
            _before_intent_review=before_intent, _before_rename_review=before_rename,
            _sync_rename_parents=True)
        return {**result, 'fixture_only': True, 'production_authorized': False}
