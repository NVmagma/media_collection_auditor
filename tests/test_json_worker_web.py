"""Current dashboard routes dispatch only the explicitly selected JSON worker."""
from unittest.mock import Mock
import pytest
from test_integration_api import api,AUTH
from test_json_worker_cycle import cycle_case
from test_json_move_execution import move_case
from test_json_worker_service import service
from app import json_worker_service
import web


@pytest.fixture
def page(api,cycle_case,monkeypatch):
    monkeypatch.setenv('AUDITOR_WORKER_MODE','json_serialized')
    monkeypatch.setenv('AUDITOR_STATE_BACKEND','json')
    monkeypatch.setattr(web,'current_user',lambda:{'admin':True,'name':'Tester'})
    worker=service(cycle_case); monkeypatch.setattr(json_worker_service,'SERVICE',worker)
    monkeypatch.setattr(web,'STATE_FILE',str(cycle_case[0].path))
    monkeypatch.setattr(web,'request_run',lambda:pytest.fail('No legacy run'))
    return api[0],worker,cycle_case


def test_manual_live_requires_confirmation_and_running_status_disables_reentry(page):
    client,worker,_=page; headers={'Origin':'http://localhost'}
    assert client.post('/api/run-now',headers=headers).status_code == 409
    assert client.post('/api/run-now',json={'run_live_scan':True},headers=headers).status_code == 202
    assert client.get('/api/run-status').json == dict(ok=True,running=False,queued=True,blocked=False)
    assert client.post('/api/run-now',json={'run_live_scan':True},headers=headers).status_code == 409
    worker.run_once(trigger='manual')
    response=client.post('/api/run-now',json={'run_live_scan':True},headers=headers)
    assert response.status_code == 429 and int(response.headers['Retry-After']) == 3600


def test_integration_token_and_foreign_origin_cannot_queue(page,monkeypatch):
    client,worker,_=page
    assert client.post('/api/run-now',json={'run_live_scan':True},headers={'Origin':'http://outside.invalid'}).status_code == 403
    monkeypatch.setattr(web,'current_user',lambda:None)
    assert client.post('/api/run-now',json={'run_live_scan':True},headers={**AUTH,'Origin':'http://localhost'}).status_code == 401
    assert not worker.report()['queued']


def test_settings_use_apply_without_typed_phrase_but_refuse_deletion(page,monkeypatch):
    client,worker,case=page; values=case[1]
    monkeypatch.setattr(web,'load_config',lambda:values)
    save=Mock(); monkeypatch.setattr(web,'save_config',save)
    response=client.get('/settings')
    assert response.status_code == 200 and 'Apply Requested Settings' in response.text
    assert 'Type I UNDERSTAND' not in response.text
    form={key:values.get(key,web.DEFAULTS.get(key,'')) for key in web.KEYS}
    form.update(settings_action='apply',MAX_ACTIONS_PER_RUN='2',ENABLE_TV='false')
    assert client.post('/settings',data=form,headers={'Origin':'http://localhost'}).status_code == 302
    assert save.call_args.args[0]['ENABLE_TV'] == 'false'
    save.reset_mock(); form['ALLOW_PERMANENT_DELETE']='true'
    response=client.post('/settings',data=form,headers={'Origin':'http://localhost'})
    assert response.status_code == 200 and 'Unsupported destructive policy' in response.text
    save.assert_not_called()


def test_scan_history_api_uses_json_worker_and_does_not_start_collection(page):
    client,worker,_=page
    worker.request(); worker.run_once(trigger='manual')
    response=client.get('/api/v1/scan-history',headers=AUTH)
    assert response.status_code == 200
    assert 'synthetic-token' not in response.text
    assert client.get('/api/v1/audit-status',headers=AUTH).json['storage_authority'] == 'json'
