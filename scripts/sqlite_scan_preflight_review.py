"""GET-only scan preparation diagnostic for an existing bound SQLite worker.

Stream into the current image. Does not claim a slot, checkpoint discovery,
dispatch a move, send Arr updates, or clear pending operations. It observes new
inputs; it cannot reconstruct the exact cause of an earlier failed attempt.
"""
from datetime import datetime
import json
from pathlib import Path
import traceback

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_arr_catalog import configured_arr_queue_resolver
from app.sqlite_backend_gate import require_sqlite_read_authority
from app.sqlite_lock import audit_run_lock
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_scheduled_configured_slot import _configured_run_inputs
from app.sqlite_scheduled_production import _hold_control_database
from app.sqlite_scheduled_worker import prepare_scheduled_worker
from app.state_store import GuardedSQLiteStateStore


def diagnose(*, settings=None):
    stage = 'binding_validation'
    result = {'read_only': True, 'media_actions_performed': False,
        'arr_updates_sent': 0, 'daily_claims_modified': False,
        'historical_failure_reconstructed': False}
    try:
        values = require_sqlite_read_authority(settings=settings)
        stage = 'worker_locks'
        database = Path(values['SQLITE_STATE_FILE'])
        with audit_run_lock(values['STATE_FILE']) as verify_json:
            with _hold_control_database(database.parent, database) as verify_control:
                session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
                state, revision = session.read_verified_snapshot()
                result['state_revision'] = revision
                def verify():
                    verify_json(); verify_control()
                    session.read_verified_snapshot()
                    if require_sqlite_read_authority(settings=settings) != values:
                        raise RuntimeError('Binding changed')
                verify()
                stage = 'pending_operation_check'
                if INTENTS_KEY in state:
                    raise RuntimeError('Pending operation')
                stage = 'collector_configuration'
                config, scan, _ = _configured_run_inputs(settings=values, clock=datetime.now,
                    allow_dry_run=True)
                stage = 'scan_preparation'
                prepared = prepare_scheduled_worker(config=config, snapshot=state,
                    revision=revision, fetch_signals=scan, now=datetime.now(),
                    discover_clocks=True)
                verify()
                changes = len(prepared.clock_proposal.changes)
                result.update(discovery_changes=changes, proposed_moves=len(prepared.plan.moves),
                    scanned_titles=prepared.plan.scanned_titles)
                if changes:
                    # Do not pretend the suppressed pre-checkpoint plan is final,
                    # and never invoke the checkpointing worker in a diagnostic.
                    result.update(status='discovery_checkpoint_required', diagnostic_stage=stage)
                    return result
                stage = 'arr_catalog_resolution'
                requests = configured_arr_queue_resolver(settings=values, config=config)(prepared)
                verify()
                result.update(status='scan_preflight_reads_complete',
                    diagnostic_stage=stage, arr_requests_prepared=len(requests),
                    execution_verified=False)
                return result
    except Exception as error:
        # Code locations identify a failing check without exception text,
        # configuration values, connection URLs, tokens or remote payloads.
        frames = traceback.extract_tb(error.__traceback__)[-6:]
        result.update(status='scan_preflight_review_blocked', diagnostic_stage=stage,
            error_type=type(error).__name__, locations=[
                {'file': Path(frame.filename).name, 'line': frame.lineno} for frame in frames])
        return result


if __name__ == '__main__':
    report = diagnose()
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(2 if report['status'] == 'scan_preflight_review_blocked' else 0)
