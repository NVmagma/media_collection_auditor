"""Read-only rolling live-scan cooldown from durable retained attempt claims.

The worker rechecks this under its existing cross-process scan lock before
creating a claim. No claim is removed, repaired or treated as retry permission.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import math
import os
import re
import stat
from zoneinfo import ZoneInfo

from app.sqlite_json import parse_unique_json
from app.sqlite_release_recovery import _local
from app.sqlite_scheduled_paths import _open_directory

INTERVAL_SECONDS = 3600
MAX_CLAIMS = 10000


class LiveScanCooldown(RuntimeError):
    pass


def manual_live_key(schedule, now):
    value = now.astimezone(timezone.utc).isoformat()
    return hashlib.sha256(('manual-live\0'+schedule.timezone_name+'\0'+value).encode()).hexdigest()+'.json'


def live_scan_status(*, control, schedule, now):
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Aware live scan time required')
    current = now.astimezone(timezone.utc)
    root = _open_directory(str(control))
    folder = None
    latest = None
    try:
        try:
            folder = os.open('.sqlite_scheduled_slots', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        except FileNotFoundError:
            return {'status': 'ready', 'next_allowed_at': None, 'retry_after_seconds': 0}
        initial = os.fstat(folder)
        if initial.st_uid != os.geteuid() or stat.S_IMODE(initial.st_mode) != 0o700:
            raise RuntimeError('Live attempt history requires review')
        names = sorted(os.listdir(folder))
        if len(names) > MAX_CLAIMS or any(not re.fullmatch(r'[0-9a-f]{64}\.json', name) for name in names):
            raise RuntimeError('Live attempt history requires review')
        identities = {}
        total = 0
        for name in names:
            info = os.stat(name, dir_fd=folder, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or not 0 < info.st_size <= 1024*1024):
                raise RuntimeError('Incomplete or unsafe live attempt requires review')
            raw, info = _local(folder, name)
            total += len(raw)
            if total > 16*1024*1024:
                raise RuntimeError('Live attempt history limit exceeded')
            identities[name] = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size)
            record = parse_unique_json(raw)
            if (not isinstance(record, dict) or type(record.get('schema_version')) is not int
                    or record['schema_version'] not in (1, 2) or record.get('phase') != 'slot_claimed'
                    or record.get('timezone') != schedule.timezone_name
                    or record.get('automatic_replay') is not False
                    or record.get('trigger', 'scheduled') not in ('scheduled', 'manual')):
                raise RuntimeError('Unrecognized live attempt requires review')
            stamp = record.get('started_at') if record['schema_version'] == 2 else record.get('scheduled_at')
            if not isinstance(stamp, str):
                raise RuntimeError('Unknown live attempt time requires review')
            started = datetime.fromisoformat(stamp)
            slot = datetime.fromisoformat(record['scheduled_at'])
            if started.tzinfo is None or slot.tzinfo is None:
                raise RuntimeError('Unknown live attempt time requires review')
            started, slot = started.astimezone(timezone.utc), slot.astimezone(timezone.utc)
            date = slot.astimezone(ZoneInfo(schedule.timezone_name)).date().isoformat()
            expected = hashlib.sha256((schedule.timezone_name+'\0'+date).encode()).hexdigest()+'.json'
            if record['schema_version'] == 2 and record.get('trigger') == 'manual':
                expected = manual_live_key(schedule, started)
                if started != slot:
                    raise RuntimeError('Manual attempt identity changed')
            if record.get('local_date') != date or expected != name:
                raise RuntimeError('Live attempt identity changed')
            latest = started if latest is None else max(latest, started)
        if sorted(os.listdir(folder)) != names:
            raise RuntimeError('Live attempt history changed')
        for name, identity in identities.items():
            info = os.stat(name, dir_fd=folder, follow_symlinks=False)
            if (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size) != identity:
                raise RuntimeError('Live attempt changed')
        actual = os.stat('.sqlite_scheduled_slots', dir_fd=root, follow_symlinks=False)
        if (actual.st_dev, actual.st_ino) != (initial.st_dev, initial.st_ino):
            raise RuntimeError('Live attempt directory changed')
    finally:
        if folder is not None:
            os.close(folder)
        os.close(root)
    eligible = None if latest is None else latest + timedelta(seconds=INTERVAL_SECONDS)
    remaining = 0 if eligible is None else max(0, math.ceil((eligible-current).total_seconds()))
    return {'status': 'cooldown' if remaining else 'ready',
            'next_allowed_at': eligible.isoformat() if remaining else None,
            'retry_after_seconds': remaining}
