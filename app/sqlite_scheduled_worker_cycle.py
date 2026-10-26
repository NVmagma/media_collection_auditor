"""Daily worker cycle state machine; no threads, sleeps or production activation.

Call once on startup, then on clock/settings/manual wake events. Only a due daily
slot can reach the supplied worker. Durable claims remain the restart boundary;
this in-memory cycle never catches up or retries failed attempts.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from app.sqlite_run_schedule import DailyRunSchedule


@dataclass(frozen=True)
class DailyCycleResult:
    status: str
    next_run: datetime
    scheduled_at: datetime | None = None
    outcome: object = None


class ScheduledWorkerCycle:
    """Calculate due attempts, advancing the next slot before invoking a worker."""
    def __init__(self):
        self._schedule = None
        self._next = None
        self._last_seen = None

    @property
    def next_run(self):
        return self._next

    def step(self, *, now, local_time, timezone_name, run_due):
        if (not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None
                or not callable(run_due)):
            raise ValueError('Aware current time and due-worker callback required')
        current = now.astimezone(timezone.utc)
        schedule = DailyRunSchedule(local_time, timezone_name)
        # Reconfigure/restart/clock rewind calculates a strictly future slot.
        # It never treats a stale date or a manual wake as a due permit.
        if (schedule != self._schedule or self._next is None
                or (self._last_seen is not None and current < self._last_seen)):
            self._schedule = schedule
            self._next = schedule.next_start(current)
            self._last_seen = current
            return DailyCycleResult('waiting', self._next)
        self._last_seen = current
        if current < self._next:
            return DailyCycleResult('waiting', self._next)
        slot = self._next
        # Advance before the callback: exceptions/uncertain outcomes cannot
        # schedule a retry. The durable per-local-date claim independently
        # protects competing processes and restarts.
        self._next = schedule.next_start(current)
        if (current - slot).total_seconds() >= 60:
            return DailyCycleResult('missed_slot_skipped', self._next, slot)
        return DailyCycleResult('attempted', self._next, slot, run_due(slot, current))

