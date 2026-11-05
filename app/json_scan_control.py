from app.tracking_schema import has_pending_extension
"""Isolated JSON scan admission and operation journal; no media/HTTP executor.

Caller holds a JsonTrackingStore session for the whole scan. Ordinary setting
changes do not rebind storage. Only an unresolved external operation blocks a
new scan beyond cooldown; an interrupted scan with no journal can start fresh.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import re
import secrets

KEY = 'json_worker_control'
INTERVAL_SECONDS = 3600


class ScanAdmissionBlocked(RuntimeError):
    def __init__(self, reason, retry_after_seconds=0):
        super().__init__(reason)
        self.reason, self.retry_after_seconds = reason, retry_after_seconds


def _time(value):
    if isinstance(value, str): value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Aware scan timestamp required')
    return value.astimezone(timezone.utc)


def _control(state):
    value = state.get(KEY)
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'last_started_at',
            'last_result', 'trigger', 'journal'} or type(value['schema_version']) is not int
            or value['schema_version'] != 1 or value['last_result'] not in
            ('imported', 'running', 'completed', 'failed')
            or value['trigger'] not in ('imported', 'manual', 'scheduled')):
        raise ScanAdmissionBlocked('scan_control_requires_review')
    _time(value['last_started_at'])
    journal = value['journal']
    if journal is not None and (not isinstance(journal, dict) or set(journal) !=
            {'id', 'kind', 'library', 'title', 'details', 'phase'}
            or not isinstance(journal['id'], str) or re.fullmatch('[0-9a-f]{32}', journal['id']) is None
            or journal['kind'] not in ('move', 'arr_sync', 'arr_import', 'arr_delete', 'orphan_quarantine')
            or journal['library'] not in ('Movies', 'TV')
            or not isinstance(journal['title'], str) or not journal['title']
            or not isinstance(journal['details'], dict) or not journal['details']
            or journal['phase'] != 'intent_recorded'):
        raise ScanAdmissionBlocked('operation_journal_requires_review')
    return value


def initialize_control(session, *, previous_started_at):
    """Offline initialization from a separately verified latest scan time.

    Never infer a fresh installation from absent metadata or drop archived claims.
    Migration is responsible for proving previous_started_at from the old claims.
    """
    session.verify()
    if KEY in session.state or has_pending_extension(session.state) or session.state.get('arr_sync_pending'):
        raise ScanAdmissionBlocked('existing_control_or_operation')
    started = _time(previous_started_at)
    session.state[KEY] = {'schema_version':1, 'last_started_at':started.isoformat(),
        'last_result':'imported', 'trigger':'imported', 'journal':None}
    session.checkpoint()


def admission_status(state, *, now):
    now = _time(now)
    value = _control(state)
    if value['journal'] is not None or has_pending_extension(state) or state.get('arr_sync_pending'):
        return {'status':'review_required', 'retry_after_seconds':0, 'next_allowed_at':None}
    eligible = _time(value['last_started_at']) + timedelta(seconds=INTERVAL_SECONDS)
    remaining = max(0, math.ceil((eligible-now).total_seconds()))
    return {'status':'cooldown' if remaining else 'ready', 'retry_after_seconds':remaining,
        'next_allowed_at':eligible.isoformat() if remaining else None}


class ScanAttempt:
    def __init__(self, session):
        self.session = session
        self._finished = False
        self._move_counts = {}

    def _active(self):
        self.session.verify()
        value = _control(self.session.state)
        if self._finished or value['last_result'] != 'running':
            raise RuntimeError('Scan attempt is not active')
        return value

    def record_intent(self, *, kind, library, title, details):
        value = self._active()
        if value['journal'] is not None:
            raise ScanAdmissionBlocked('operation_requires_review')
        if (kind not in ('move', 'arr_sync', 'arr_import', 'arr_delete', 'orphan_quarantine') or library not in ('Movies','TV')
                or not isinstance(title, str) or not title or len(title) > 250
                or any(ord(c) < 32 or c in '/\\' for c in title)
                or not isinstance(details, dict) or not details):
            raise ValueError('Known operation and title required')
        identifier = secrets.token_hex(16)
        value['journal'] = {'id':identifier, 'kind':kind, 'library':library,
            'title':title, 'details':deepcopy(details), 'phase':'intent_recorded'}
        self.session.checkpoint()  # The executor may act only after this returns.
        return identifier

    def finish_operation(self, *, identifier, verify_outcome):
        """Trusted executor supplies fresh outcome verification, never browser input."""
        value = self._active()
        journal = deepcopy(value['journal'])
        if journal is None or journal['id'] != identifier or not callable(verify_outcome):
            raise ValueError('Exact pending operation and verifier required')
        before = deepcopy(self.session.state)
        if verify_outcome(deepcopy(journal)) is not True:
            raise ScanAdmissionBlocked('operation_outcome_unverified')
        self.session.verify()
        if self.session.state != before or _control(self.session.state)['journal'] != journal:
            raise ScanAdmissionBlocked('operation_changed')
        value['journal'] = None
        self.session.checkpoint()

    def finish(self, *, result):
        value = self._active()
        if result not in ('completed', 'failed'): raise ValueError('Known result required')
        if value['journal'] is not None:
            raise ScanAdmissionBlocked('operation_requires_review')
        value['last_result'] = result
        self.session.checkpoint()
        self._finished = True


@contextmanager
def scan_attempt(store, *, now, trigger):
    if trigger not in ('manual', 'scheduled'): raise ValueError('Known scan trigger required')
    now = _time(now)
    with store.session() as session:
        status = admission_status(session.state, now=now)
        if status['status'] != 'ready':
            raise ScanAdmissionBlocked(status['status'], status['retry_after_seconds'])
        value = _control(session.state)
        value.update(last_started_at=now.isoformat(), last_result='running', trigger=trigger)
        session.checkpoint()  # Cooldown survives restart and failed scans.
        yield ScanAttempt(session)
        # No implicit completion, journal clearance or save on exit/exception.
