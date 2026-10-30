"""Durable rolling cooldown shared by scheduled/manual attempts, across restarts."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path

import pytest
from app.sqlite_live_cooldown import live_scan_status, LiveScanCooldown
from app.sqlite_scheduled_slot import _claim_scheduled_slot_locked
from app.sqlite_run_schedule import DailyRunSchedule

NOW=datetime(2026,10,30,9,tzinfo=timezone.utc)
SCHEDULE=DailyRunSchedule('02:00','America/Los_Angeles')


def status(root,now=NOW):
    return live_scan_status(control=root,schedule=SCHEDULE,now=now)


def claim(root,now,manual=True):
    return _claim_scheduled_slot_locked(root=root,schedule=SCHEDULE,scheduled_at=now,
        now=now,verify_binding=lambda:None,manual=manual,live_hourly=True)


def test_cooldown_is_rolling_not_clock_hour_and_survives_new_reader(tmp_path):
    start=NOW+timedelta(minutes=59)
    with claim(tmp_path,start):pass
    assert status(tmp_path,start+timedelta(minutes=1))['retry_after_seconds']==3540
    assert status(tmp_path,start+timedelta(seconds=3599))['status']=='cooldown'
    with pytest.raises(LiveScanCooldown):
        with claim(tmp_path,start+timedelta(seconds=3599)):pytest.fail('early claim')
    with claim(tmp_path,start+timedelta(hours=1)):pass
    assert len(list((tmp_path/'.sqlite_scheduled_slots').iterdir()))==2


def test_scheduled_and_manual_share_interval_and_daily_schedule_key(tmp_path):
    with claim(tmp_path,NOW,manual=False):pass
    with pytest.raises(LiveScanCooldown):
        with claim(tmp_path,NOW+timedelta(minutes=30)):pytest.fail('extra attempt')
    with claim(tmp_path,NOW+timedelta(hours=1)):pass
    assert len(list((tmp_path/'.sqlite_scheduled_slots').iterdir()))==2


def test_failed_attempt_consumes_cooldown_and_clock_rewind_cannot_bypass(tmp_path):
    with pytest.raises(RuntimeError,match='fixture'):
        with claim(tmp_path,NOW):raise RuntimeError('fixture')
    assert status(tmp_path,NOW-timedelta(days=1))['status']=='cooldown'
    assert status(tmp_path,NOW+timedelta(minutes=59))['status']=='cooldown'


def test_legacy_daily_claim_is_respected_without_limiting_whole_date(tmp_path):
    with _claim_scheduled_slot_locked(root=tmp_path,schedule=SCHEDULE,scheduled_at=NOW,
        now=NOW,verify_binding=lambda:None):pass
    before=next((tmp_path/'.sqlite_scheduled_slots').iterdir()).read_bytes()
    assert status(tmp_path,NOW+timedelta(minutes=59))['status']=='cooldown'
    with claim(tmp_path,NOW+timedelta(hours=1)):pass
    assert before in [p.read_bytes() for p in (tmp_path/'.sqlite_scheduled_slots').iterdir()]


@pytest.mark.parametrize('kind',['empty','invalid','symlink','hardlink','unknown_name'])
def test_partial_or_unsafe_claim_never_creates_retry_permission(tmp_path,kind):
    with claim(tmp_path,NOW):pass
    folder=tmp_path/'.sqlite_scheduled_slots';path=folder/('f'*64+'.json')
    if kind=='symlink':path.symlink_to(next(folder.iterdir()))
    elif kind=='hardlink':os.link(next(folder.iterdir()),path)
    elif kind=='unknown_name':(folder/'unknown.json').write_bytes(b'{}')
    else:path.write_bytes(b'' if kind=='empty' else b'{}');path.chmod(0o600)
    with pytest.raises((RuntimeError,OSError,ValueError)):
        status(tmp_path,NOW+timedelta(days=1))


def test_local_midnight_and_dst_repeat_do_not_reset_interval(tmp_path):
    midnight=NOW.replace(hour=6,minute=30)+timedelta(days=1)
    with claim(tmp_path,midnight):pass
    assert status(tmp_path,midnight+timedelta(minutes=31))['status']=='cooldown'
    with claim(tmp_path,midnight+timedelta(hours=1)):pass
    # Fall-back repeats 01:xx locally, but sixty elapsed UTC minutes still apply.
    autumn=datetime(2026,11,1,8,30,tzinfo=timezone.utc)
    with claim(tmp_path,autumn):pass
    assert status(tmp_path,autumn+timedelta(minutes=59))['status']=='cooldown'
    with claim(tmp_path,autumn+timedelta(hours=1)):pass


def test_actual_controller_sigkill_keeps_claim_and_cooldown(tmp_path):
    import signal
    import subprocess
    import sys
    code='''
from datetime import datetime
import os,signal,sys
from app.sqlite_run_schedule import DailyRunSchedule
from app.sqlite_scheduled_slot import _claim_scheduled_slot_locked
now=datetime.fromisoformat(sys.argv[2])
with _claim_scheduled_slot_locked(root=sys.argv[1],schedule=DailyRunSchedule('02:00','America/Los_Angeles'),
    scheduled_at=now,now=now,verify_binding=lambda:None,manual=True,live_hourly=True):
    os.kill(os.getpid(),signal.SIGKILL)
'''
    child=subprocess.run([sys.executable,'-B','-c',code,str(tmp_path),NOW.isoformat()],timeout=15)
    assert child.returncode==-signal.SIGKILL
    assert status(tmp_path,NOW+timedelta(minutes=59))['status']=='cooldown'
    assert status(tmp_path,NOW+timedelta(hours=1))['status']=='ready'
