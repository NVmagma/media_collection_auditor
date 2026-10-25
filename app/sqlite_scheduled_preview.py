"""Read-only scheduled collection; no clock checkpoint, move or Arr dispatch.

The caller owns the daily claim and cooperating source/control locks. Discovery
proposals remain advisory; their presence suppresses move proposals until a live
run can checkpoint and freshly rebuild. A preview never authorizes execution.
"""
from datetime import timezone
import math

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_scheduled_worker import prepare_scheduled_worker
from app.state_store import GuardedSQLiteStateStore


def prepare_scheduled_preview(*, database, config, fetch_signals, scheduled_at,
        clock, timer, verify_binding, maximum_scan_seconds=3600, started_tick=None):
    started = timer() if started_tick is None else started_tick
    def remaining():
        elapsed = timer() - started
        if not math.isfinite(elapsed) or not 0 <= elapsed < maximum_scan_seconds:
            raise RuntimeError('Scheduled preview deadline exceeded')
        return maximum_scan_seconds - elapsed
    remaining()
    verify_binding()
    session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
    snapshot, revision = session.read_verified_snapshot()
    if INTENTS_KEY in snapshot:
        raise RuntimeError('Unresolved SQLite operation; scheduled preview stopped')
    def read(binding):
        signals = fetch_signals(binding)
        fields = ('played', 'favorite', 'disliked', 'keep', 'keep_all', 'protected')
        if not isinstance(signals, dict) or not all(type(signals.get(key)) is bool for key in fields):
            raise RuntimeError('Scheduled preview protection unavailable')
        return signals
    prepared = prepare_scheduled_worker(config=config, snapshot=snapshot,
        revision=revision, fetch_signals=read, now=clock(), timer=timer,
        maximum_scan_seconds=remaining(), discover_clocks=True)
    verify_binding()
    # Includes raw same-revision changes and independent checkpoint races.
    session.read_verified_snapshot()
    remaining()
    return {'status': 'scheduled_preview_complete', 'dry_run': True,
        'scheduled_at': scheduled_at.astimezone(timezone.utc).isoformat(),
        'scanned_titles': prepared.plan.scanned_titles,
        'proposed_moves': prepared.plan.moves,
        'discovery_changes': len(prepared.clock_proposal.changes),
        'discovery_checkpoint_required': bool(prepared.clock_proposal.changes),
        'completed': (), 'arr_completed': (), 'clock_checkpointed': False,
        'initial_revision': revision, 'final_revision': revision,
        'production_authorized': False, 'production_activation': 'disabled'}
