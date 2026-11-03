"""Offline cooldown initialization from a retained attempt archive; no replay."""
import base64
from datetime import datetime, timezone
import hashlib
import re
from zoneinfo import ZoneInfo

from app.json_scan_control import initialize_control
from app.sqlite_json import parse_unique_json


def latest_archived_start(archive, *, timezone_name):
    zone = ZoneInfo(timezone_name)
    if (not isinstance(archive,dict) or set(archive) != {'present','entries'}
            or archive['present'] is not True or not isinstance(archive['entries'],dict)
            or not 1 <= len(archive['entries']) <= 10000):
        raise ValueError('Complete nonempty attempt archive required')
    latest, total = None, 0
    for name,encoded in archive['entries'].items():
        if (not isinstance(name,str) or re.fullmatch(r'[0-9a-f]{64}\.json',name) is None
                or not isinstance(encoded,str) or len(encoded) > 1400000):
            raise ValueError('Recognized attempt entry required')
        raw = base64.b64decode(encoded,validate=True); total += len(raw)
        if not 0 < len(raw) <= 1024*1024 or total > 16*1024*1024:
            raise ValueError('Complete bounded attempt required')
        row = parse_unique_json(raw)
        if (not isinstance(row,dict) or type(row.get('schema_version')) is not int
                or row['schema_version'] not in (1,2) or row.get('phase') != 'slot_claimed'
                or row.get('timezone') != timezone_name or row.get('automatic_replay') is not False
                or row.get('trigger','scheduled') not in ('manual','scheduled')):
            raise ValueError('Recognized attempt history required')
        start = datetime.fromisoformat(row['started_at'] if row['schema_version'] == 2 else row['scheduled_at'])
        slot = datetime.fromisoformat(row['scheduled_at'])
        if start.tzinfo is None or slot.tzinfo is None: raise ValueError('Aware attempt timestamps required')
        start,slot = start.astimezone(timezone.utc),slot.astimezone(timezone.utc)
        date = slot.astimezone(zone).date().isoformat()
        identity = timezone_name+'\0'+date
        if row['schema_version'] == 2 and row.get('trigger') == 'manual':
            if start != slot: raise ValueError('Manual attempt timestamps disagree')
            identity = 'manual-live\0'+timezone_name+'\0'+start.isoformat()
        expected = hashlib.sha256(identity.encode()).hexdigest()+'.json'
        if name != expected or row.get('local_date') != date:
            raise ValueError('Attempt identity mismatch')
        latest = start if latest is None else max(latest,start)
    return latest


def initialize_from_archive(store, *, archive, timezone_name):
    latest = latest_archived_start(archive,timezone_name=timezone_name)
    with store.session() as session:
        initialize_control(session,previous_started_at=latest)
    return {'status':'json_cooldown_initialized','latest_started_at':latest.isoformat(),
        'archived_attempts':len(archive['entries']),'media_actions_performed':False,
        'arr_updates_sent':0,'archive_modified':False,'automatic_replay':False}
