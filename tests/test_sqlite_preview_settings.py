"""Settings requests preserve active preview bytes and private state."""
import json
import stat
from unittest.mock import Mock
import pytest
from app.sqlite_preview_settings import request_settings, PENDING
from app.config_store import DEFAULTS


def configured(tmp_path):
    active=tmp_path/'auditor_config.json'
    values={**DEFAULTS,'DRY_RUN':'true','ALLOW_PERMANENT_DELETE':'false',
        'ALLOW_FILESYSTEM_DELETE':'false','ALLOW_CROSS_FILESYSTEM_MOVES':'false',
        'ENABLE_SEASON_PRUNING':'false','ENABLE_TV':'false','private_extension':{'value':'retained'}}
    active.write_text(json.dumps(values))
    return active,values


def test_tv_request_preserves_active_bytes_and_unknown_settings(tmp_path):
    active,values=configured(tmp_path); original=active.read_bytes()
    result=request_settings(config_path=active,updated={**values,'ENABLE_TV':'true'},environment={})
    assert result=={'status':'requested','active_settings_changed':False}
    assert active.read_bytes()==original
    requested=json.loads((tmp_path/PENDING).read_bytes())
    assert requested['requested_config']['ENABLE_TV']=='true'
    assert requested['requested_config']['private_extension']==values['private_extension']
    assert stat.S_IMODE((tmp_path/PENDING).stat().st_mode)==0o600


def test_unchanged_save_writes_nothing(tmp_path):
    active,values=configured(tmp_path)
    assert request_settings(config_path=active,updated=values,environment={})['status']=='unchanged'
    assert sorted(x.name for x in tmp_path.iterdir())==[active.name]


@pytest.mark.parametrize('key',['DRY_RUN','ALLOW_FILESYSTEM_DELETE','ALLOW_PERMANENT_DELETE','ALLOW_CROSS_FILESYSTEM_MOVES','ENABLE_SEASON_PRUNING'])
def test_preview_cannot_request_media_actions(tmp_path,key):
    active,values=configured(tmp_path); original=active.read_bytes()
    values[key]='false' if key=='DRY_RUN' else 'true'
    with pytest.raises(ValueError): request_settings(config_path=active,updated=values,environment={})
    assert active.read_bytes()==original and not (tmp_path/PENDING).exists()


def test_invalid_binding_keeps_login_settings_and_health_available(preview,monkeypatch):
    client,observer,wake,check=preview
    check.side_effect=RuntimeError('private-token')
    assert client.get('/login').status_code in (200,302)
    assert client.get('/health').status_code==200
    response=client.get('/')
    assert response.status_code==503 and 'private-token' not in response.text
    assert 'Preview scans are paused' in response.text
    import web
    monkeypatch.setattr(web,'load_config',lambda:{})
    assert client.get('/settings').status_code==200
    assert observer.report()['queued'] is not True
    wake.assert_not_called()


def test_preview_never_queues_json_after_backend_change(preview,monkeypatch):
    client,observer,wake,check=preview
    monkeypatch.setenv('AUDITOR_STATE_BACKEND','json')
    check.side_effect=RuntimeError('bad backend')
    assert client.post('/api/run-now',headers={'Origin':'http://localhost'}).status_code==409
    assert observer.report()['queued'] is not True


from test_sqlite_manual_preview_web import preview

from test_integration_api import api


def test_admin_save_stages_request_without_invalidating_active_settings(preview,monkeypatch,tmp_path):
    client,observer,wake,check=preview
    import config_store,web
    active,values=configured(tmp_path); original=active.read_bytes()
    monkeypatch.setattr(config_store,'CONFIG_FILE',str(active))
    monkeypatch.setattr(web,'load_config',lambda:dict(values))
    legacy=Mock(side_effect=AssertionError('Active config must not be overwritten'))
    monkeypatch.setattr(web,'save_config',legacy)
    form={key:values.get(key, 'false' if key in web.BOOLS else '') for key in web.KEYS}
    form['ENABLE_TV']='true'
    response=client.post('/settings',data=form,headers={'Origin':'http://localhost'})
    assert response.status_code==302 and 'requested=1' in response.location
    assert active.read_bytes()==original
    assert json.loads((tmp_path/PENDING).read_bytes())['requested_config']['ENABLE_TV']=='true'
    legacy.assert_not_called(); wake.assert_not_called()


def test_settings_reload_failure_keeps_service_loop_alive(monkeypatch):
    from app import sqlite_scheduled_service as service,sqlite_backend_gate as gate
    import run_control
    monkeypatch.setattr(gate,'preview_release_enabled',lambda:True)
    calls=[]
    class EndTest(BaseException): pass
    def wait(delay):
        calls.append(delay)
        raise EndTest
    monkeypatch.setattr(run_control,'wait_for_run',wait)
    collect=Mock(side_effect=AssertionError('No collection on invalid settings'))
    monkeypatch.setattr(service,'production_cycle_step',collect)
    with pytest.raises(EndTest):
        service.run_daily_service(apply_settings=Mock(side_effect=ValueError('private-settings')))
    assert calls==[30]
    collect.assert_not_called()
