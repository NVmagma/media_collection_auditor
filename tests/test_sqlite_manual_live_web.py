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
    claimed=Mock(return_value=False);monkeypatch.setattr(worker,'_daily_claim_exists',claimed)
    observer=observations.ScheduledRunObservations();monkeypatch.setattr(observations,'COORDINATOR',observer)
    wake=Mock();monkeypatch.setattr(run_control,'wake_worker',wake)
    legacy=Mock(side_effect=AssertionError('No legacy worker'));monkeypatch.setattr(web,'request_run',legacy)
    return api[0],observer,wake,claimed,check


def post(client,**kwargs):
    return client.post('/api/run-now',json={'consume_daily_slot':True},headers={'Origin':'http://localhost'},**kwargs)


def test_explicit_live_confirmation_queues_only_one_request(page):
    client,observer,wake,_,_=page
    assert client.post('/api/run-now',headers={'Origin':'http://localhost'}).status_code==409
    response=post(client)
    assert response.status_code==202 and 'one-action budget' in response.json['message']
    assert observer.report()['queued'] is True
    assert post(client).status_code==409
    wake.assert_called_once()


def test_claimed_daily_budget_never_queues_or_wakes(page):
    client,observer,wake,claimed,_=page;claimed.return_value=True
    assert post(client).status_code==409
    assert observer.report()['queued'] is not True;wake.assert_not_called()


def test_invalid_binding_is_redacted_and_not_queued(page):
    client,observer,wake,_,check=page;check.side_effect=RuntimeError('private-token')
    response=post(client)
    assert response.status_code==409 and 'private-token' not in response.text
    assert observer.report()['queued'] is not True;wake.assert_not_called()


def test_readonly_integration_token_and_cross_origin_cannot_start_live(page,monkeypatch):
    client,observer,wake,_,_=page
    assert client.post('/api/run-now',json={'consume_daily_slot':True},headers={'Origin':'http://outside.invalid'}).status_code==403
    monkeypatch.setattr(web,'current_user',lambda:None)
    assert client.post('/api/run-now',json={'consume_daily_slot':True},headers={**AUTH,'Origin':'http://localhost'}).status_code==401
    assert observer.report()['queued'] is not True;wake.assert_not_called()


@pytest.mark.parametrize('data',[None,{}, {'consume_daily_slot':False}, {'consume_daily_slot':1},
    {'consume_daily_slot':'true'}, {'consume_daily_slot':True,'maximum_actions':10}])
def test_confirmation_requires_exact_true_without_policy_overrides(page,data):
    client,observer,wake,_,_=page
    assert client.post('/api/run-now',json=data,headers={'Origin':'http://localhost'}).status_code==409
    assert observer.report()['queued'] is not True;wake.assert_not_called()
