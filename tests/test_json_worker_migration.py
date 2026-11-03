"""Archived attempt conversion never resets clocks or releases partial claims."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from zoneinfo import ZoneInfo

import pytest
from app.json_worker_migration import latest_archived_start, initialize_from_archive
from app.json_scan_control import KEY, admission_status
from test_json_tracking_store import store

ZONE = 'America/Los_Angeles'
NOW = datetime(2026,1,10,12,tzinfo=timezone.utc)


def claim(start,manual=True):
    date = start.astimezone(ZoneInfo(ZONE)).date().isoformat()
    identity = 'manual-live\0'+ZONE+'\0'+start.isoformat() if manual else ZONE+'\0'+date
    name = hashlib.sha256(identity.encode()).hexdigest()+'.json'
    row = {'schema_version':2,'phase':'slot_claimed','timezone':ZONE,'local_date':date,
        'automatic_replay':False,'trigger':'manual' if manual else 'scheduled',
        'scheduled_at':start.isoformat(),'started_at':start.isoformat()}
    return name,base64.b64encode(json.dumps(row).encode()).decode()


def archive():
    return {'present':True,'entries':dict([claim(NOW-timedelta(days=1),False),claim(NOW-timedelta(minutes=20))])}


def test_latest_start_preserves_hourly_budget_and_all_tracking(store):
    history = archive(); before = deepcopy(history),json.loads(store.path.read_bytes())
    report = initialize_from_archive(store,archive=history,timezone_name=ZONE)
    assert report['latest_started_at'] == (NOW-timedelta(minutes=20)).isoformat()
    assert not report['archive_modified'] and history == before[0]
    current = json.loads(store.path.read_bytes())
    assert {k:v for k,v in current.items() if k != KEY} == before[1]
    assert admission_status(current,now=NOW)['retry_after_seconds'] == 2400
    raw = store.path.read_bytes()
    with pytest.raises(RuntimeError): initialize_from_archive(store,archive=history,timezone_name=ZONE)
    assert store.path.read_bytes() == raw


@pytest.mark.parametrize('change',['empty','partial','corrupt','name','zone','naive','date','replay'])
def test_incomplete_or_changed_archive_never_initializes_control(store,change):
    history = archive(); name = next(iter(history['entries']))
    row = json.loads(base64.b64decode(history['entries'][name]))
    if change == 'empty': history['entries'] = {}
    elif change == 'partial': history['entries'][name] = ''
    elif change == 'corrupt': history['entries'][name] = '!notbase64'
    elif change == 'name': history['entries']['0'*64+'.json'] = history['entries'].pop(name)
    else:
        if change == 'zone': row['timezone'] = 'UTC'
        elif change == 'naive': row['started_at'] = '2026-01-01'
        elif change == 'date': row['local_date'] = '2026-01-01'
        else: row['automatic_replay'] = True
        history['entries'][name] = base64.b64encode(json.dumps(row).encode()).decode()
    raw = store.path.read_bytes()
    with pytest.raises((ValueError,RuntimeError)):
        initialize_from_archive(store,archive=history,timezone_name=ZONE)
    assert store.path.read_bytes() == raw


def test_unsorted_archive_uses_latest_not_first_or_last_entry():
    history = archive()
    assert latest_archived_start(history,timezone_name=ZONE) == NOW-timedelta(minutes=20)
    history['entries'] = dict(reversed(list(history['entries'].items())))
    assert latest_archived_start(history,timezone_name=ZONE) == NOW-timedelta(minutes=20)
