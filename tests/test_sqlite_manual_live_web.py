from unittest.mock import Mock
import pytest
from app import sqlite_backend_gate as gate
from app import sqlite_scheduled_observations as observations
from app import sqlite_scheduled_production as worker
from test_integration_api import api,AUTH
import web,run_control

@pytest.fixture
def page(api,monkeypatch):
    monkeypatch.setenv('AUDITOR_STATE_BACKEND','sqlite')
    monkeypatch.setattr(web,'current_user',lambda:{'name':'Admin','admin':True})
    monkeypatch.setattr(gate,'preview_release_enabled',lambda:False)
    monkeypatch.setattr(gate,'live_release_enabled',lambda:True)
    check=Mock(return_value={});monkeypatch.setattr(gate,'require_sqlite_production_activation',check)
    claimed=Mock(return_value={'status':'ready'});monkeypatch.setattr(worker,'_live_scan_status',claimed)
    observer=observations.ScheduledRunObservations();monkeypatch.setattr(observations,'COORDINATOR',observer)
    wake=Mock();monkeypatch.setattr(run_control,'wake_worker',wake)
    legacy=Mock(side_effect=AssertionError('No legacy worker'));monkeypatch.setattr(web,'request_run',legacy)
    return api[0],observer,wake,claimed,check


def post(client,**kwargs):
    return client.post('/api/run-now',json={'run_live_scan':True},headers={'Origin':'http://localhost'},**kwargs)


def test_explicit_live_confirmation_queues_only_one_request(page):
    client,observer,wake,_,_=page
    assert client.post('/api/run-now',headers={'Origin':'http://localhost'}).status_code==409
    response=post(client)
    assert response.status_code==202 and '60 minutes' in response.json['message']
    assert observer.report()['queued'] is True
    assert post(client).status_code==409
    wake.assert_called_once()


def test_hourly_cooldown_never_queues_or_wakes(page):
    client,observer,wake,claimed,_=page;claimed.return_value={'status':'cooldown','next_allowed_at':'2026-10-30T12:00:00+00:00','retry_after_seconds':120}
    response=post(client)
    assert response.status_code==429 and response.headers['Retry-After']=='120'
    assert response.json['next_allowed_at']=='2026-10-30T12:00:00+00:00'
    assert observer.report()['queued'] is not True;wake.assert_not_called()


def test_invalid_binding_is_redacted_and_not_queued(page):
    client,observer,wake,_,check=page;check.side_effect=RuntimeError('private-token')
    response=post(client)
    assert response.status_code==409 and 'private-token' not in response.text
    assert observer.report()['queued'] is not True;wake.assert_not_called()


def test_readonly_integration_token_and_cross_origin_cannot_start_live(page,monkeypatch):
    client,observer,wake,_,_=page
    assert client.post('/api/run-now',json={'run_live_scan':True},headers={'Origin':'http://outside.invalid'}).status_code==403
    monkeypatch.setattr(web,'current_user',lambda:None)
    assert client.post('/api/run-now',json={'run_live_scan':True},headers={**AUTH,'Origin':'http://localhost'}).status_code==401
    assert observer.report()['queued'] is not True;wake.assert_not_called()


@pytest.mark.parametrize('data',[None,{}, {'run_live_scan':False}, {'run_live_scan':1},
    {'run_live_scan':'true'}, {'run_live_scan':True,'maximum_actions':10}])
def test_confirmation_requires_exact_true_without_policy_overrides(page,data):
    client,observer,wake,_,_=page
    assert client.post('/api/run-now',json=data,headers={'Origin':'http://localhost'}).status_code==409
    assert observer.report()['queued'] is not True;wake.assert_not_called()



def test_active_scan_blocks_new_request_even_after_cooldown(page):
    from datetime import datetime,timezone
    from threading import Event,Thread
    client,observer,wake,_,_=page
    active,release=Event(),Event()
    def execute():
        active.set()
        assert release.wait(5)
        return {'status':'disposable_scheduled_routed_slot_complete','completed':()}
    thread=Thread(target=lambda:observer.run_attempt(scheduled_at=datetime.now(timezone.utc),execute=execute))
    thread.start()
    try:
        assert active.wait(5)
        response=post(client)
        assert response.status_code==409 and 'running or queued' in response.json['message']
        wake.assert_not_called()
    finally:
        release.set();thread.join(timeout=5)


def test_run_button_status_reports_queue_without_starting_or_exposing_payload(page):
    client, observer, wake, _, check = page
    assert client.get('/api/run-status').json == {'ok': True, 'running': False, 'queued': False}
    observer.request_manual_live()
    response = client.get('/api/run-status')
    assert response.json == {'ok': True, 'running': False, 'queued': True}
    assert response.headers['Cache-Control'] == 'no-store'
    wake.assert_not_called()
    check.assert_not_called()
