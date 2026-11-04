"""Isolated scan admission/journal; never performs media or Arr operations."""
from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys

import pytest
from app.json_tracking_store import JsonTrackingStore
from app.json_scan_control import (KEY, ScanAdmissionBlocked, admission_status,
    initialize_control, scan_attempt)
from test_json_tracking_store import store

NOW = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)


@pytest.fixture
def initialized(store):
    with store.session() as session:
        initialize_control(session, previous_started_at=NOW-timedelta(hours=2))
    return store


def test_manual_and_scheduled_share_persistent_hourly_cooldown(initialized):
    original = json.loads(initialized.path.read_bytes())
    with scan_attempt(initialized, now=NOW, trigger='manual') as attempt:
        attempt.finish(result='completed')
    before = initialized.path.read_bytes()
    # A new object/process sees the same persisted budget, not a daily limit.
    for trigger in ('manual','scheduled'):
        with pytest.raises(ScanAdmissionBlocked) as caught:
            with scan_attempt(JsonTrackingStore(initialized.path),
                    now=NOW+timedelta(minutes=59), trigger=trigger): pass
        assert caught.value.reason == 'cooldown' and caught.value.retry_after_seconds == 60
    assert initialized.path.read_bytes() == before
    with scan_attempt(initialized, now=NOW+timedelta(hours=1), trigger='scheduled') as attempt:
        attempt.finish(result='completed')
    result = json.loads(initialized.path.read_bytes())
    assert {k:v for k,v in result.items() if k != KEY} == {k:v for k,v in original.items() if k != KEY}


def test_other_process_cannot_begin_during_active_scan(initialized):
    code = '''import sys
from datetime import datetime
from app.json_tracking_store import JsonTrackingStore
from app.json_scan_control import scan_attempt
from app.state_lock import StateLockBusy
try:
 with scan_attempt(JsonTrackingStore(sys.argv[1]), now=datetime.fromisoformat(sys.argv[2]), trigger="manual"):
  raise SystemExit(9)
except StateLockBusy: raise SystemExit(0)
'''
    with scan_attempt(initialized, now=NOW, trigger='scheduled'):
        result = subprocess.run([sys.executable,'-B','-c',code,str(initialized.path),
            (NOW+timedelta(hours=2)).isoformat()], timeout=10)
        assert result.returncode == 0


def test_interrupted_scan_without_operation_can_start_fresh_after_cooldown(initialized):
    with pytest.raises(RuntimeError):
        with scan_attempt(initialized, now=NOW, trigger='manual') as attempt:
            attempt.session.state['first_seen'].clear()
            raise RuntimeError('synthetic private exception')
    current = json.loads(initialized.path.read_bytes())
    assert current['first_seen'] and current[KEY]['last_result'] == 'running'
    with scan_attempt(initialized, now=NOW+timedelta(hours=1), trigger='manual') as attempt:
        attempt.finish(result='failed')
    assert 'synthetic private' not in initialized.path.read_text()


def test_intent_is_durable_before_executor_and_blocks_restart_without_replay(initialized):
    with scan_attempt(initialized, now=NOW, trigger='manual') as attempt:
        identifier = attempt.record_intent(kind='arr_sync', library='TV', title='Existing show',
            details={'path':'/media/TV_keep/Existing show', 'monitored':True})
        assert json.loads(initialized.path.read_bytes())[KEY]['journal']['id'] == identifier
        with pytest.raises(ScanAdmissionBlocked): attempt.finish(result='completed')
    before = initialized.path.read_bytes()
    with pytest.raises(ScanAdmissionBlocked) as caught:
        with scan_attempt(initialized, now=NOW+timedelta(days=1), trigger='manual'): pass
    assert caught.value.reason == 'review_required'
    assert initialized.path.read_bytes() == before


def test_only_exact_verified_operation_can_complete(initialized):
    with scan_attempt(initialized, now=NOW, trigger='manual') as attempt:
        identifier = attempt.record_intent(kind='move', library='Movies', title='Existing',
            details={'source':'/media/Movies/Existing', 'destination':'/media/Movies_hold/Existing'})
        with pytest.raises(ValueError):
            attempt.finish_operation(identifier='0'*32, verify_outcome=lambda _: True)
        with pytest.raises(ScanAdmissionBlocked):
            attempt.finish_operation(identifier=identifier, verify_outcome=lambda _: False)
        assert json.loads(initialized.path.read_bytes())[KEY]['journal'] is not None
        seen = []
        def verify(journal):
            seen.append(journal['details']['destination'])
            journal['details'].clear()  # Verifier receives a detached copy.
            return True
        attempt.finish_operation(identifier=identifier, verify_outcome=verify)
        assert seen == ['/media/Movies_hold/Existing']
        attempt.finish(result='completed')
    assert json.loads(initialized.path.read_bytes())[KEY]['journal'] is None


@pytest.mark.parametrize('change', ['absent', 'malformed', 'old_intent', 'arr_pending'])
def test_unknown_or_unresolved_control_never_resets_or_claims(initialized, change):
    with initialized.session() as session:
        if change == 'absent': session.state.pop(KEY)
        elif change == 'malformed': session.state[KEY] = {'unknown':'preserve'}
        elif change == 'old_intent': session.state['sqlite_pending_operations'] = {'kind':'move'}
        else: session.state['arr_sync_pending']['TV/Existing'] = {
            'stage':'keep', 'root':'/media/TV_keep', 'monitored':True}
        session.checkpoint()
    before = initialized.path.read_bytes()
    with pytest.raises(ScanAdmissionBlocked):
        with scan_attempt(initialized, now=NOW, trigger='manual'): pass
    assert initialized.path.read_bytes() == before


def test_initialization_is_explicit_and_cannot_reset_existing_claims(store):
    with pytest.raises(ScanAdmissionBlocked):
        with scan_attempt(store, now=NOW, trigger='manual'): pass
    with store.session() as session:
        with pytest.raises(ValueError): initialize_control(session, previous_started_at='2026-01-01')
        initialize_control(session, previous_started_at=NOW-timedelta(minutes=20))
        with pytest.raises(ScanAdmissionBlocked): initialize_control(session, previous_started_at=NOW)
        assert admission_status(session.state, now=NOW)['retry_after_seconds'] == 2400


def test_clock_rollback_never_bypasses_cooldown(initialized):
    with initialized.session() as session:
        assert admission_status(session.state, now=NOW-timedelta(hours=3))['status'] == 'cooldown'


@pytest.mark.parametrize('journal', [False, True])
def test_actual_process_death_preserves_claim_and_optional_intent(initialized, journal):
    code = '''import os, signal, sys
from datetime import datetime
from app.json_tracking_store import JsonTrackingStore
from app.json_scan_control import scan_attempt
with scan_attempt(JsonTrackingStore(sys.argv[1]), now=datetime.fromisoformat(sys.argv[2]), trigger="manual") as attempt:
 if sys.argv[3] == "True":
  attempt.record_intent(kind="arr_sync", library="Movies", title="Existing", details={"path":"/media/Movies_hold/Existing"})
 os.kill(os.getpid(), signal.SIGKILL)
'''
    result = subprocess.run([sys.executable,'-B','-c',code,str(initialized.path), NOW.isoformat(),str(journal)], timeout=10)
    assert result.returncode == -9
    current = json.loads(initialized.path.read_bytes())
    assert current[KEY]['last_started_at'] == NOW.isoformat()
    assert admission_status(current, now=NOW+timedelta(minutes=1))['status'] == ('review_required' if journal else 'cooldown')


def test_verifier_cannot_modify_tracking_while_clearing_intent(initialized):
    with scan_attempt(initialized, now=NOW, trigger='manual') as attempt:
        identifier = attempt.record_intent(kind='arr_sync', library='TV', title='Existing',
            details={'path':'/media/TV_keep/Existing'})
        before = initialized.path.read_bytes()
        def mutate(_):
            attempt.session.state['first_seen'].clear()
            return True
        with pytest.raises(ScanAdmissionBlocked):
            attempt.finish_operation(identifier=identifier, verify_outcome=mutate)
        assert initialized.path.read_bytes() == before


def test_lost_verification_ack_never_clears_or_replays_journal(initialized):
    with scan_attempt(initialized, now=NOW, trigger='manual') as attempt:
        identifier = attempt.record_intent(kind='arr_sync', library='Movies', title='Existing',
            details={'path':'/media/Movies_hold/Existing'})
        before = initialized.path.read_bytes()
        def lost_ack(_): raise TimeoutError('synthetic private response')
        with pytest.raises(TimeoutError):
            attempt.finish_operation(identifier=identifier, verify_outcome=lost_ack)
        assert initialized.path.read_bytes() == before
    with initialized.session() as session:
        assert session.state[KEY]['journal']['id'] == identifier
