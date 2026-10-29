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


def test_manual_live_moves_one_and_timer_same_day_never_runs_again(case):
    arr=case.arr();case.bind();now=case.case.fixture.slot-timedelta(hours=1)
    assert case.step(now-timedelta(minutes=1)).status=='waiting'
    result=manual(case,now)
    assert len(result['completed'])==1 and arr.puts==1
    calls=list(case.case.server.calls);history=case.observer.history()
    assert history[0]['trigger']=='manual' and history[0]['dry_run'] is False
    assert case.step(case.case.fixture.slot).outcome['status']=='daily_slot_already_claimed'
    assert case.case.server.calls==calls and case.observer.history()==history
    # A fresh process cannot turn another manual wake into a new attempt.
    assert manual(case,now+timedelta(minutes=1),ScheduledRunObservations())['status']=='daily_slot_already_claimed'
    assert case.case.server.calls==calls and arr.puts==1


def test_timer_then_manual_has_no_extra_collection_or_arr_request(case):
    arr=case.arr();case.bind();case.due();calls=list(case.case.server.calls)
    assert manual(case,case.case.fixture.slot+timedelta(hours=1))['status']=='daily_slot_already_claimed'
    assert case.case.server.calls==calls and arr.puts==1


def test_failed_manual_scan_retains_claim_before_retry_or_timer(case):
    case.bind();now=case.case.fixture.slot-timedelta(hours=1)
    with patch('app.sqlite_scheduled_routed_slot._prepare_configured_worker_locked',side_effect=RuntimeError('scan failed')):
        with pytest.raises(RuntimeError):manual(case,now)
    calls=list(case.case.server.calls)
    assert manual(case,now+timedelta(seconds=1))['status']=='daily_slot_already_claimed'
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
