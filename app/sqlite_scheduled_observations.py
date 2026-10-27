"""Ephemeral scheduled-run observations; no tracking authority or durable history.

No JSON history fallback, credential/free-text capture, network or state writes.
The durable daily claim and operation intent remain the replay authority.
"""
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4


class ScheduledRunObservations:
    def __init__(self, *, clock=lambda: datetime.now(timezone.utc)):
        self._clock = clock
        self._lock = Lock()
        self._observed = False
        self._running = False
        self._manual_pending = False
        self._manual_claimed = False
        self._next_run = None
        self._scheduler_state = 'unobserved'
        self._history = []
        self._active = None

    def _now(self):
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError('Aware observation clock required')
        return value.astimezone(timezone.utc).isoformat()

    def observe_cycle(self, *, next_run, status):
        if status not in ('waiting', 'missed_slot_skipped', 'attempted', 'blocked'):
            raise ValueError('Known scheduler observation required')
        if not isinstance(next_run, datetime) or next_run.tzinfo is None:
            raise ValueError('Aware next schedule required')
        with self._lock:
            self._observed = True
            self._next_run = next_run.astimezone(timezone.utc).isoformat()
            self._scheduler_state = status

    def invalidate_schedule(self):
        with self._lock:
            self._observed = True
            self._next_run = None
            self._scheduler_state = 'blocked'

    def request_manual_preview(self):
        with self._lock:
            if self._running or self._manual_pending or self._manual_claimed:
                return False
            self._manual_pending = True
            self._observed = True
            return True

    def claim_manual_preview(self):
        with self._lock:
            if not self._manual_pending or self._running or self._manual_claimed:
                return False
            self._manual_pending = False
            self._manual_claimed = True
            return True

    def cancel_pending_preview(self):
        with self._lock:
            self._manual_pending = False

    def release_manual_preview(self):
        with self._lock:
            self._manual_claimed = False

    def run_attempt(self, *, scheduled_at, execute, dry_run=False, trigger='scheduled'):
        if type(dry_run) is not bool:
            raise ValueError('Explicit dry-run observation required')
        if not callable(execute) or not isinstance(scheduled_at, datetime) or scheduled_at.tzinfo is None:
            raise ValueError('Bound scheduled attempt required')
        if trigger not in ('scheduled', 'manual') or (trigger == 'manual' and not dry_run):
            raise ValueError('Manual observations require read-only preview')
        record = {'id': uuid4().hex, 'trigger': trigger, 'dry_run': dry_run,
            'scheduled_at': scheduled_at.astimezone(timezone.utc).isoformat(),
            'started_at': self._now(), 'finished_at': None, 'result': None,
            'movies_processed': None, 'tv_processed': None,
            'moves_completed': None, 'arr_completed': None, 'state_revision': None,
            'moves_proposed': None, 'discovery_changes': None,
            'result_basis': 'worker_return', 'freshness_verified': False,
            'history_scope': 'current_process'}
        with self._lock:
            if self._running or (self._manual_claimed and trigger != 'manual'):
                raise RuntimeError('Scheduled observation already active')
            if trigger == 'manual' and not self._manual_claimed:
                raise RuntimeError('Explicit manual request required')
            self._manual_claimed = False
            self._observed = True; self._running = True; self._active = record
        result = None
        try:
            result = execute()
            expected = 'scheduled_preview_complete' if dry_run else 'disposable_scheduled_routed_slot_complete'
            success = isinstance(result, dict) and result.get('status') == expected
            record['result'] = 'completed' if success else 'failed'
            if isinstance(result, dict):
                if dry_run:
                    proposed = result.get('proposed_moves')
                    if isinstance(proposed, tuple) and len(proposed) <= 100000:
                        record['moves_proposed'] = len(proposed)
                    changes = result.get('discovery_changes')
                    if type(changes) is int and 0 <= changes <= 100000:
                        record['discovery_changes'] = changes
                moves = result.get('completed')
                if isinstance(moves, tuple) and len(moves) <= 100000:
                    record['moves_completed'] = len(moves)
                arr = result.get('arr_completed')
                if isinstance(arr, tuple) and len(arr) <= 100000:
                    record['arr_completed'] = len(arr)
                revision = result.get('final_revision')
                if type(revision) is int and revision >= 0:
                    record['state_revision'] = revision
            return result
        except BaseException:
            record['result'] = 'failed'
            record['result_basis'] = 'blocked_or_uncertain'
            raise
        finally:
            try:
                record['finished_at'] = self._now()
            except (ValueError, TypeError, OverflowError):
                record['finished_at'] = None
                record['result'] = 'failed'
                record['result_basis'] = 'observation_unavailable'
            with self._lock:
                self._running = False; self._active = None
                self._history.append(deepcopy(record))
                self._history = self._history[-100:]

    def history(self, limit=100):
        if type(limit) is not int or not 0 <= limit <= 100:
            raise ValueError('History limit must be 0 through 100')
        with self._lock:
            return deepcopy(list(reversed(self._history[-limit:]))) if limit else []

    def report(self):
        with self._lock:
            return self._report_locked()

    def capture(self):
        """One detached process observation and history under the same lock."""
        with self._lock:
            return {'run': self._report_locked(),
                    'history': deepcopy(list(reversed(self._history)))}

    def _report_locked(self):
        latest = self._active if self._running else (self._history[-1] if self._history else {})
        return {'schema_version': 1, 'status': 'advisory_only' if self._observed else 'unavailable',
            'source': 'sqlite_scheduler_process', 'storage_authority': 'sqlite_candidate',
            'read_only': True, 'production_activation': 'disabled', 'production_authorized': False,
            'freshness_verified': False, 'history_scope': 'current_process', 'history_persistent': False,
            'running': self._running if self._observed else None,
            'queued': (self._manual_pending or self._manual_claimed) if self._observed else None, 'rescuing': False if self._observed else None,
            'scheduler_state': self._scheduler_state, 'next_run': self._next_run,
            'last_started': latest.get('started_at'), 'last_finished': None if self._running else latest.get('finished_at'),
            'last_result': None if self._running else latest.get('result'), 'last_trigger': latest.get('trigger'),
            'result_basis': latest.get('result_basis'),
            'state_revision': latest.get('state_revision'), 'moves_completed': latest.get('moves_completed'),
            'dry_run': latest.get('dry_run'), 'moves_proposed': latest.get('moves_proposed'),
            'discovery_changes': latest.get('discovery_changes')}


COORDINATOR = ScheduledRunObservations()
