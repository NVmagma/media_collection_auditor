"""Operator runs share the durable daily budget with timer and restart paths."""
from datetime import timedelta
from unittest.mock import patch
from scripts import sqlite_live_release_fixture as release_fixture
from app import sqlite_release_profile as build
from app.sqlite_scheduled_production import run_requested_live
from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle
from app.sqlite_scheduled_observations import ScheduledRunObservations
import pytest

@pytest.fixture
def case(monkeypatch):
    case=release_fixture.LiveReleaseTests();case.setUp()
    monkeypatch.setattr(build,'PROFILE','scheduled-live-moves-v1')
    monkeypatch.setattr(build,'SOURCE_REVISION','b'*40)
    try:yield case
    finally:case.doCleanups()


def manual(case,when,observer=None):
    from scripts.sqlite_scheduled_configured_slot_fixture import NOW
    observer=case.observer if observer is None else observer
    assert observer.request_manual_live()
    return run_requested_live(settings=case.values,now=when,observer=observer,clock=lambda:NOW)


def test_manual_live_moves_one_and_timer_within_hour_is_skipped(case):
    arr=case.arr();case.bind();now=case.case.fixture.slot-timedelta(minutes=30)
    assert case.step(now-timedelta(minutes=1)).status=='waiting'
    result=manual(case,now)
    assert len(result['completed'])==1 and arr.puts==1
    calls=list(case.case.server.calls);history=case.observer.history()
    assert history[0]['trigger']=='manual' and history[0]['dry_run'] is False
    assert case.step(case.case.fixture.slot).outcome['status']=='live_scan_cooldown'
    assert case.case.server.calls==calls and case.observer.history()==history
    # A fresh process cannot turn another manual wake into a new attempt.
    assert manual(case,now+timedelta(minutes=1),ScheduledRunObservations())['status']=='live_scan_cooldown'
    assert case.case.server.calls==calls and arr.puts==1


def test_timer_then_manual_can_run_again_after_sixty_minutes(case):
    arr=case.arr();case.bind();case.due();calls=list(case.case.server.calls)
    assert manual(case,case.case.fixture.slot+timedelta(minutes=59,seconds=59))['status']=='live_scan_cooldown'
    assert case.case.server.calls==calls and arr.puts==1
    result=manual(case,case.case.fixture.slot+timedelta(hours=1))
    assert len(result['completed'])==1 and arr.puts==2


def test_failed_manual_scan_retains_claim_before_retry_or_timer(case):
    case.bind();now=case.case.fixture.slot-timedelta(minutes=30)
    with patch('app.sqlite_scheduled_routed_slot._prepare_configured_worker_locked',side_effect=RuntimeError('scan failed')):
        with pytest.raises(RuntimeError):manual(case,now)
    calls=list(case.case.server.calls)
    assert manual(case,now+timedelta(seconds=1))['status']=='live_scan_cooldown'
    assert case.case.server.calls==calls


def test_sealed_or_preview_image_cannot_consume_live_request(case,monkeypatch):
    case.bind();before=case.store.load_with_revision()
    for profile in ('sealed','scheduled-preview-v1'):
        monkeypatch.setattr(build,'PROFILE',profile)
        with pytest.raises(RuntimeError):manual(case,case.case.fixture.slot)
    assert case.store.load_with_revision()==before and case.case.server.calls==[]


def test_releasing_finished_request_does_not_drop_a_new_queued_request():
    from datetime import datetime,timezone
    observer=ScheduledRunObservations()
    assert observer.request_manual_live() and observer.claim_manual_live()
    observer.run_attempt(scheduled_at=datetime.now(timezone.utc),dry_run=False,trigger='manual',
        execute=lambda:{'status':'disposable_scheduled_routed_slot_complete','completed':()})
    assert observer.request_manual_live()
    observer.release_manual_preview()
    assert observer.claim_manual_live()


def test_refresh_hook_runs_once_after_move_and_arr_commit(case):
    arr = case.arr(); case.bind()
    before = case.store.load_with_revision()
    def refresh(**kwargs):
        from app.sqlite_operation_coordinator import INTENTS_KEY
        assert len(kwargs['result']['completed']) == 1
        assert arr.puts == 1
        state, revision = case.store.load_with_revision()
        assert revision > before[1] and INTENTS_KEY not in state
        return {'status': 'requested', 'scan_completion_verified': False}
    with patch('app.sqlite_jellyfin_refresh.refresh_after_completed_live_run', side_effect=refresh) as hook:
        result = manual(case, case.case.fixture.slot)
    hook.assert_called_once()
    assert result['jellyfin_refresh']['status'] == 'requested'


def test_two_library_live_slots_move_one_movie_and_one_show_and_deliver_both_arr(case):
    arr = case.arr()
    case.values['MAX_ACTIONS_PER_RUN'] = '2'
    case.bind()
    before = case.store.load_with_revision()
    result = manual(case, case.case.fixture.slot)
    assert [row['library'] for row in result['completed']] == ['Movies', 'TV']
    assert len(result['completed']) == 2 and arr.puts == 2
    state, revision = case.store.load_with_revision()
    assert revision > before[1]
    assert set(state['queued']) >= {'Same (2020)', 'TV/Same (2020)'}
    assert state['arr_sync_pending'] == before[0]['arr_sync_pending']
    assert case.source.read_bytes() == case.original
    assert manual(case, case.case.fixture.slot + timedelta(minutes=59))['status'] == 'live_scan_cooldown'
    assert arr.puts == 2
