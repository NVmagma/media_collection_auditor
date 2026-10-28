"""Notification hooks cannot change worker claims, settings outcomes or tracking."""
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.operational_notifications import OperationalNotifications
from app.sqlite_scheduled_observations import ScheduledRunObservations


class EndTest(BaseException):pass


def service_case(monkeypatch,step,*,cycles=3,gate_failure=False):
    from app import sqlite_scheduled_service as service,sqlite_backend_gate as gate
    import app.sqlite_scheduled_observations as observations
    import run_control
    for key,value in {'AUDITOR_STATE_BACKEND':'sqlite','NOTIFY_OPERATIONAL_FAILURES':'true',
        'NOTIFY_ON_DRY_RUN':'true','DRY_RUN':'true','NOTIFY_WEBHOOK_URL':'http://fixture.invalid/private'}.items():monkeypatch.setenv(key,value)
    observer=ScheduledRunObservations()
    send=Mock(return_value=True)
    alerts=OperationalNotifications(deliver=send)
    monkeypatch.setattr(service,'NOTIFICATIONS',alerts)
    monkeypatch.setattr(observations,'COORDINATOR',observer)
    monkeypatch.setattr(gate,'preview_release_enabled',lambda:True)
    def require():
        if gate_failure:raise RuntimeError('private-token-do-not-log')
    monkeypatch.setattr(service,'require_sqlite_production_activation',require)
    monkeypatch.setattr(service,'production_cycle_step',lambda **kw:step(observer))
    monkeypatch.setattr(service,'run_requested_preview',lambda **kw:None)
    waits=[]
    def wait(delay):
        waits.append(delay)
        if len(waits)>=cycles:raise EndTest
    monkeypatch.setattr(run_control,'wait_for_run',wait)
    with pytest.raises(EndTest):service.run_daily_service(apply_settings=lambda:None)
    return send,waits,observer


def test_repeated_scheduler_exception_is_one_redacted_delivery(monkeypatch,capsys):
    def step(observer):raise RuntimeError('private-token-do-not-log')
    send,waits,_=service_case(monkeypatch,step)
    assert send.call_count==1 and waits==[30,30,30]
    assert send.call_args.args[3]['event']=='scan_blocked_or_uncertain'
    assert 'private-token-do-not-log' not in capsys.readouterr().out


def test_binding_review_alert_deduplicates_without_worker(monkeypatch):
    send,_,_=service_case(monkeypatch,lambda *_:pytest.fail('No invalid worker run'),gate_failure=True)
    assert send.call_count==1
    assert send.call_args.args[3]['event']=='settings_review_required'


def test_waiting_cycle_does_not_rearm_failed_scan_alert(monkeypatch):
    count=0
    def step(observer):
        nonlocal count
        count+=1
        if count==2:return SimpleNamespace(status='waiting',next_run=datetime.now(timezone.utc)+timedelta(hours=1))
        raise RuntimeError('private')
    send,_,_=service_case(monkeypatch,step)
    assert send.call_count==1


def test_completed_attempt_rearms_later_incident(monkeypatch):
    count=0
    def step(observer):
        nonlocal count
        count+=1
        if count!=2:raise RuntimeError('private')
        observer.run_attempt(scheduled_at=datetime.now(timezone.utc),dry_run=True,
            execute=lambda:{'status':'scheduled_preview_complete'})
        return SimpleNamespace(status='attempted',next_run=datetime.now(timezone.utc)+timedelta(days=1))
    send,_,_=service_case(monkeypatch,step)
    assert send.call_count==2


def test_failed_record_without_exception_still_alerts(monkeypatch):
    def step(observer):
        observer.run_attempt(scheduled_at=datetime.now(timezone.utc),dry_run=True,execute=lambda:{'status':'unexpected'})
        return SimpleNamespace(status='attempted',next_run=datetime.now(timezone.utc)+timedelta(days=1))
    send,_,observer=service_case(monkeypatch,step,cycles=1)
    assert send.call_count==1 and observer.report()['last_result']=='failed'
