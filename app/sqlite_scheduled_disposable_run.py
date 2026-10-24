"""One due daily slot: durable claim -> full scan -> bounded disposable batch.

No production worker/backend selection. The existing disposable marker/database
and cooperating runner lock are mandatory throughout collection and execution.
"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from time import monotonic

from app.sqlite_scheduled_disposable_batch import _execute_scheduled_batch_locked
from app.sqlite_scheduled_plan import collect_scheduled_plan
from app.sqlite_scheduled_slot import claim_disposable_scheduled_slot
from app.state_store import GuardedSQLiteStateStore


def run_disposable_scheduled_slot(*, root, schedule, scheduled_at, now, libraries,
        scan_library, title_folders, fetch_protection, maximum_actions=10,
        maximum_titles=100000, maximum_scan_seconds=3600, maximum_protection_seconds=30,
        favorites_trigger_keep=True, clock=datetime.now, timer=monotonic, fault_at=None, arr_sync_requests=None):
    root = Path(root)
    requests = deepcopy(arr_sync_requests)
    with claim_disposable_scheduled_slot(root=root, schedule=schedule,
            scheduled_at=scheduled_at, now=now) as verify_claim:
        database = root / 'state.db'
        state, revision = GuardedSQLiteStateStore(database).load_with_revision()
        # If collection raises, the retained slot claim forbids this slot's replay.
        plan = collect_scheduled_plan(snapshot=state, revision=revision, libraries=libraries,
            scan_library=scan_library, now=clock(), maximum_actions=maximum_actions,
            maximum_titles=maximum_titles, maximum_scan_seconds=maximum_scan_seconds,
            favorites_trigger_keep=favorites_trigger_keep, timer=timer)
        verify_claim()
        folders = {move.media_key: title_folders[move.media_key] for move in plan.moves}
        return _execute_scheduled_batch_locked(root=root, database=database, plan=plan,
            title_folders=folders, fetch_protection=fetch_protection, clock=clock, timer=timer,
            maximum_protection_seconds=maximum_protection_seconds, fault_at=fault_at,
            verify_binding=verify_claim, arr_sync_requests=requests)
