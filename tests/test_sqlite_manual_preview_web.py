from unittest.mock import Mock
import pytest
from app import sqlite_backend_gate as gate
from app import sqlite_scheduled_observations as observations
from test_integration_api import api, AUTH
import web
import run_control


@pytest.fixture
def preview(api, monkeypatch):
    monkeypatch.setenv('AUDITOR_STATE_BACKEND','sqlite')
    monkeypatch.setattr(web,'current_user',lambda:{'name':'Admin','admin':True})
    monkeypatch.setattr(gate,'preview_release_enabled',lambda:True)
    check=Mock(return_value={'DRY_RUN':'true'})
    monkeypatch.setattr(gate,'require_sqlite_production_activation',check)
    observer=observations.ScheduledRunObservations()
    monkeypatch.setattr(observations,'COORDINATOR',observer)
    wake=Mock(); monkeypatch.setattr(run_control,'wake_worker',wake)
    legacy=Mock(side_effect=AssertionError('No legacy audit request'))
    monkeypatch.setattr(web,'request_run',legacy)
    return api[0],observer,wake,check


def test_admin_same_origin_can_queue_one_readonly_preview(preview):
    client,observer,wake,check=preview
    response=client.post('/api/run-now',headers={'Origin':'http://localhost'})
    assert response.status_code==202 and observer.report()['queued'] is True
    assert 'Daily schedule unchanged' in response.json['message']
    wake.assert_called_once(); check.assert_called_once()
    assert client.post('/api/run-now',headers={'Origin':'http://localhost'}).status_code==409
    assert wake.call_count==1


@pytest.mark.parametrize('origin',[None,'http://different.invalid'])
def test_manual_preview_requires_same_origin(preview,origin):
    client,observer,wake,_=preview
    assert client.post('/api/run-now',headers={} if origin is None else {'Origin':origin}).status_code==403
    assert observer.report()['queued'] is not True; wake.assert_not_called()


def test_integration_bearer_cannot_queue_manual_scan(preview,monkeypatch):
    client,observer,wake,_=preview
    monkeypatch.setattr(web,'current_user',lambda:None)
    assert client.post('/api/run-now',headers={**AUTH,'Origin':'http://localhost'}).status_code==401
    assert observer.report()['queued'] is not True; wake.assert_not_called()


def test_non_admin_cannot_queue_manual_scan(preview,monkeypatch):
    client,observer,wake,_=preview
    monkeypatch.setattr(web,'current_user',lambda:{'name':'Viewer','admin':False})
    assert client.post('/api/run-now',headers={'Origin':'http://localhost'}).status_code==403
    assert observer.report()['queued'] is not True; wake.assert_not_called()


def test_changed_binding_refuses_queue_without_exposing_details(preview):
    client,observer,wake,check=preview
    check.side_effect=RuntimeError('private-token')
    response=client.post('/api/run-now',headers={'Origin':'http://localhost'})
    assert response.status_code==409 and 'private-token' not in response.get_data(as_text=True)
    assert observer.report()['queued'] is not True; wake.assert_not_called()


def test_sealed_sqlite_backend_stays_daily_only(preview,monkeypatch):
    client,observer,wake,check=preview
    monkeypatch.setattr(gate,'preview_release_enabled',lambda:False)
    assert client.post('/api/run-now',headers={'Origin':'http://localhost'}).status_code==409
    assert observer.report()['queued'] is not True
    check.assert_not_called(); wake.assert_not_called()
