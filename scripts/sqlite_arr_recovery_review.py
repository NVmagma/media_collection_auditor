"""Review a retained Arr intent, with a separate explicit reconciliation option.

May be streamed to the running image with ``docker exec -i ... python -B -``.
Only imports modules already present in the live release. Private state and
credentials are never printed, including on failure.
The default is read-only. Reconciliation requires a previously reviewed exact
fingerprint, a bound live image and fresh verification under both worker locks.
"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import re

from app.sqlite_arr_catalog import ArrCatalogGET, canonical_arr_record_path
from app.sqlite_arr_queue_plan import planned_arr_queue_entry
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_isolated_arr_runner import STAGES
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_scheduled_paths import _open_directory
from app.sqlite_scheduled_settings import scheduled_worker_from_settings
from app.state_store import GuardedSQLiteStateStore


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
        allow_nan=False, separators=(',', ':')).encode('ascii')).hexdigest()


def review(*, settings):
    """Observe a stable local snapshot and two fresh, exact remote catalog reads.

    This is an observation at review time, not proof of the original HTTP
    acknowledgment or the original moved inode. No SQLite writes are offered.
    """
    with _verified_review(settings=settings) as (report, session, key, verify):
        return report


@contextmanager
def _verified_review(*, settings, verify_authority=lambda: None, expected_fingerprint=None):
    """Keep descriptors and a verified session alive through explicit clearance."""
    verify_authority()
    values = dict(settings)
    config = scheduled_worker_from_settings(values)
    database = Path(values['SQLITE_STATE_FILE'])
    with ExitStack() as stack:
        db_fd = os.open(database, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        stack.callback(os.close, db_fd)
        if not stat.S_ISREG(os.fstat(db_fd).st_mode):
            raise RuntimeError('Database unavailable')
        session = RevisionedAuditSession(GuardedSQLiteStateStore(database))
        state, revision = session.read_verified_snapshot()
        intent = deepcopy(state.get(INTENTS_KEY))
        if (not isinstance(intent, dict)
                or set(intent) != {'id', 'kind', 'phase', 'details'}
                or not isinstance(intent['id'], str) or not intent['id']
                or intent['kind'] != 'arr_sync'
                or intent['phase'] not in ('intent_recorded', 'applied_pending_reconciliation')):
            raise RuntimeError('Exact Arr intent required')
        details = intent['details']
        if not isinstance(details, dict) or set(details) != {
                'service', 'title_id', 'root', 'monitored', 'media_key', 'title_folder', 'stage'}:
            raise RuntimeError('Exact Arr details required')
        request = {key: details[key] for key in ('service', 'title_id', 'root', 'monitored')}
        key, folder, stage = (details[name] for name in ('media_key', 'title_folder', 'stage'))
        queue = planned_arr_queue_entry(request=request, media_key=key,
            title_folder=folder, destination_stage=stage)
        if state['arr_sync_pending'].get(key) != queue:
            raise RuntimeError('Queue mismatch')
        clocks = ('first_seen', 'queued', 'keep_seen', 'in_removal')
        if key not in state[STAGES[stage]] or any(key in state[name]
                for name in clocks if name != STAGES[stage]):
            raise RuntimeError('Unique destination clock required')
        library_name = 'Movies' if request['service'] == 'radarr' else 'TV'
        libraries = [lib for lib in config.libraries if lib.name == library_name]
        if len(libraries) != 1:
            raise RuntimeError('Enabled bound library required')
        stage_names = {'Waiting': 'transient', 'Holding': 'holding',
                       'Keep': 'keep', 'Removal': 'removal'}
        roots = {stage_names[name]: path for name, path in libraries[0].roots}
        # APP_* aliases are remote paths and intentionally need not equal local roots.
        expected = request['root'] + '/' + folder
        parents = {}
        for name, path in roots.items():
            fd = _open_directory(path)
            stack.callback(os.close, fd)
            parents[name] = fd
        title_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            | os.O_NONBLOCK, dir_fd=parents[stage])
        stack.callback(os.close, title_fd)

        def identity(info):
            return (info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns, info.st_ctime_ns)

        held_title = identity(os.fstat(title_fd))

        def verify():
            verify_authority()
            held_db = os.fstat(db_fd)
            current_db = database.stat(follow_symlinks=False)
            if (held_db.st_dev, held_db.st_ino) != (current_db.st_dev, current_db.st_ino):
                raise RuntimeError('Database replaced')
            present = []
            for name, fd in parents.items():
                held, current = os.fstat(fd), os.stat(roots[name], follow_symlinks=False)
                if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
                    raise RuntimeError('Stage replaced')
                try:
                    entry = os.stat(folder, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISDIR(entry.st_mode):
                    raise RuntimeError('Unsafe title')
                present.append(name)
                if name == stage and identity(entry) != held_title:
                    raise RuntimeError('Destination changed')
            if present != [stage]:
                raise RuntimeError('Ambiguous destination')
            session.read_verified_snapshot()

        verify()
        fingerprint = _digest({'state': state, 'revision': revision,
            'destination_identity': held_title})
        if expected_fingerprint is not None and fingerprint != expected_fingerprint:
            raise RuntimeError('Reviewed state changed')
        prefix = 'RADARR' if request['service'] == 'radarr' else 'SONARR'
        for _ in range(2):
            records = ArrCatalogGET(service=request['service'],
                base_url=values[prefix + '_URL'], token=values[prefix + '_API_KEY'])()
            verify()
            matches = [record for record in records if isinstance(record, dict)
                and type(record.get('id')) is int and record['id'] == request['title_id']]
            if (len(matches) != 1 or canonical_arr_record_path(matches[0].get('path')) != expected
                    or type(matches[0].get('monitored')) is not bool
                    or matches[0]['monitored'] != request['monitored']):
                raise RuntimeError('Remote readback mismatch')
        verify()
        report = {'status': 'arr_recovery_review_matches', 'read_only': True,
            'state_revision': revision, 'review_fingerprint': fingerprint,
            'pending_kind': 'arr_sync', 'pending_phase': intent['phase'],
            'remote_readbacks': 2, 'destination_unique': True,
            'intent_modified': False, 'media_actions_performed': False,
            'clearance_authorized': False}
        yield report, session, key, verify


def reconcile(*, expected_fingerprint, settings=None):
    """Explicit bound-live acknowledgment; GET-only, no operation replay.

    Both cooperating worker locks remain held from authority validation through
    the single queue/intent CAS. A failed checkpoint is never retried. A crash
    before commit leaves the original intent; after commit it is already gone.
    """
    if not isinstance(expected_fingerprint, str) or not re.fullmatch('[0-9a-f]{64}', expected_fingerprint):
        raise ValueError('Exact review fingerprint required')
    from app.sqlite_backend_gate import live_release_enabled, require_sqlite_read_authority
    from app.sqlite_live_policy import validate_initial_live_policy
    from app.sqlite_lock import audit_run_lock
    from app.sqlite_scheduled_production import _hold_control_database
    if not live_release_enabled():
        raise RuntimeError('Bound live image required')
    values = require_sqlite_read_authority(settings=settings)
    validate_initial_live_policy(values)
    database = Path(values['SQLITE_STATE_FILE'])
    with audit_run_lock(values['STATE_FILE']) as verify_json:
        with _hold_control_database(database.parent, database) as verify_control:
            def verify_authority():
                verify_json()
                verify_control()
                if require_sqlite_read_authority(settings=settings) != values:
                    raise RuntimeError('Live authority changed')
            with _verified_review(settings=values, verify_authority=verify_authority,
                    expected_fingerprint=expected_fingerprint) as (report, session, key, verify):
                verify()
                # These exact entries were verified against two concrete fresh
                # GETs while the destination and full tracking revision stayed
                # pinned. Never mark/replay the original remote operation.
                session.state['arr_sync_pending'].pop(key)
                session.state.pop(INTENTS_KEY)
                session.checkpoint()
                verify()
                return {'status': 'arr_intent_reconciled',
                    'review_fingerprint': expected_fingerprint,
                    'previous_revision': report['state_revision'],
                    'state_revision': session.revision, 'remote_readbacks': 2,
                    'media_actions_performed': False, 'arr_updates_sent': 0,
                    'automatic_retry': False, 'tracking_clocks_preserved': True,
                    'daily_claims_modified': False}


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Explicit Arr intent review or reconciliation')
    parser.add_argument('--reconcile-reviewed-fingerprint')
    args = parser.parse_args()
    try:
        if args.reconcile_reviewed_fingerprint is not None:
            result = reconcile(expected_fingerprint=args.reconcile_reviewed_fingerprint)
            print(json.dumps(result, sort_keys=True))
            return 0
        from app.sqlite_backend_gate import require_sqlite_read_authority
        settings = require_sqlite_read_authority()
        result = review(settings=settings)
        if require_sqlite_read_authority() != settings:
            raise RuntimeError('Authority changed during review')
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        if args.reconcile_reviewed_fingerprint is not None:
            # An I/O failure may follow a committed CAS. Never claim unchanged
            # state or offer an automatic retry on this path.
            print(json.dumps({'status': 'arr_reconciliation_blocked_or_uncertain',
                'state_change_may_have_committed': True, 'automatic_retry': False,
                'media_actions_performed': False, 'arr_updates_sent': 0}))
            return 2
        print(json.dumps({'status': 'arr_recovery_review_blocked', 'read_only': True,
            'intent_modified': False, 'media_actions_performed': False,
            'clearance_authorized': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
