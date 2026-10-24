"""Durable daily slot claims while holding a cooperating disposable runner lock.

No sleeps, catch-up, claim deletion, saved-plan replay or production entry point.
A retained claim prevents another scheduled attempt for that zone/local date.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from zoneinfo import ZoneInfo

from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_run_schedule import DailyRunSchedule


@contextmanager
def claim_disposable_scheduled_slot(*, root, schedule, scheduled_at, now, maximum_lateness_seconds=60):
    _slot_identity(schedule, scheduled_at, now, maximum_lateness_seconds)
    with isolated_runner_lock(root) as verify_binding:
        with _claim_scheduled_slot_locked(root=root, schedule=schedule, scheduled_at=scheduled_at,
                now=now, maximum_lateness_seconds=maximum_lateness_seconds,
                verify_binding=verify_binding) as verify_claim:
            yield verify_claim


@contextmanager
def _claim_scheduled_slot_locked(*, root, schedule, scheduled_at, now,
        maximum_lateness_seconds=60, verify_binding):
    """Private claim primitive; caller retains the bound control lock throughout."""
    slot, date, key = _slot_identity(schedule, scheduled_at, now, maximum_lateness_seconds)
    root = Path(root)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory_fd = record_fd = None
    try:
        try:
            os.mkdir('.sqlite_scheduled_slots', mode=0o700, dir_fd=root_fd)
            os.fsync(root_fd)
        except FileExistsError:
            pass
        directory_fd = os.open('.sqlite_scheduled_slots', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                               dir_fd=root_fd)
        info = os.fstat(directory_fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError('Unsafe slot directory')
        # Exclusive creation is the durable at-most-once attempt boundary.
        record_fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600, dir_fd=directory_fd)
        payload = json.dumps({'schema_version': 1, 'phase': 'slot_claimed',
            'scheduled_at': slot.isoformat(), 'timezone': schedule.timezone_name,
            'local_date': date, 'automatic_replay': False,
            'production_authorized': False}, sort_keys=True).encode()
        offset = 0
        while offset < len(payload):
            written = os.write(record_fd, payload[offset:])
            if written <= 0:
                raise OSError('Incomplete slot record')
            offset += written
        os.fsync(record_fd); os.fsync(directory_fd)
        verify_binding()
        def verify_claim():
            verify_binding()
            entry = os.stat('.sqlite_scheduled_slots', dir_fd=root_fd, follow_symlinks=False)
            if (entry.st_dev, entry.st_ino) != (info.st_dev, info.st_ino):
                raise RuntimeError('Slot directory replaced')
            held = os.fstat(record_fd)
            actual = os.stat(key, dir_fd=directory_fd, follow_symlinks=False)
            if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1
                    or (actual.st_dev, actual.st_ino) != (held.st_dev, held.st_ino)):
                raise RuntimeError('Slot record replaced')
        verify_claim()
        yield verify_claim
        verify_claim()
    finally:
        for fd in (record_fd, directory_fd, root_fd):
            if fd is not None:
                os.close(fd)


def _slot_identity(schedule, scheduled_at, now, maximum_lateness_seconds):
    if not isinstance(schedule, DailyRunSchedule):
        raise ValueError('Daily schedule required')
    if any(not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None
           for value in (scheduled_at, now)):
        raise ValueError('Aware slot/current timestamps required')
    if type(maximum_lateness_seconds) is not int or not 1 <= maximum_lateness_seconds <= 300:
        raise ValueError('Bounded scheduling jitter required')
    slot, current = scheduled_at.astimezone(timezone.utc), now.astimezone(timezone.utc)
    if schedule.next_start(slot - timedelta(microseconds=1)) != slot:
        raise ValueError('Timestamp is not this schedule slot')
    if not 0 <= (current - slot).total_seconds() < maximum_lateness_seconds:
        raise RuntimeError('Slot not due or missed; no catch-up')
    date = slot.astimezone(ZoneInfo(schedule.timezone_name)).date().isoformat()
    key = hashlib.sha256((schedule.timezone_name + '\0' + date).encode()).hexdigest() + '.json'
    return slot, date, key
