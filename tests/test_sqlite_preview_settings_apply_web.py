"""Authenticated application/recovery UI against a real disposable binding."""
import os
import sys
from unittest.mock import patch
import pytest

import config_store
import web
from app.sqlite_lock import state_writer_lock
from app import sqlite_preview_settings_apply as apply
from scripts.sqlite_preview_settings_apply_fixture import SettingsApplyFixtureTests as _Case

pytestmark=pytest.mark.skipif(sys.platform!='linux',reason='Linux private preview fixtures')


@pytest.fixture
def page(monkeypatch):
    case=_Case();case.setUp()
    monkeypatch.setattr(web,'current_user',lambda:{'name':'Fixture admin','admin':True})
    monkeypatch.setattr(config_store,'CONFIG_FILE',case.saved)
    monkeypatch.setattr(config_store,'initial_environment',lambda:dict(case.values))
    token='fixture-settings-integration-token-0123456789'
    with patch.dict(os.environ,{**case.values,'INTEGRATION_API_TOKEN':token}):
        try:yield web.app.test_client(),case,token
        finally:case.doCleanups()


def post(client,case,route='/settings/apply',**options):
    return client.post(route,data={'request_sha256':case.digest},headers={'Origin':'http://localhost'},**options)


def test_apply_form_preserves_tracking_and_shows_active_settings(page):
    client,case,_=page
    assert 'Apply Requested Settings' in client.get('/settings').text
    response=post(client,case)
    assert response.status_code==302 and 'applied=1' in response.location
    result=client.get(response.location)
    assert result.status_code==200 and 'Requested settings applied' in result.text
    assert 'Apply Requested Settings' in result.text
    assert 'name="request_sha256"' not in result.text
    case.unchanged_tracking()


def test_failed_application_keeps_ui_and_explicit_restore_available(page):
    client,case,token=page
    def stop(phase):
        if phase=='after_config':raise RuntimeError('secret-never-expose')
    with patch.object(apply,'_boundary',stop):response=post(client,case)
    assert 'apply_error=1' in response.location
    result=client.get('/settings')
    assert result.status_code==200 and 'Restore Previous Settings' in result.text
    assert 'secret-never-expose' not in result.text
    assert client.get('/').status_code==503
    assert client.get('/health').status_code==200
    assert client.get('/api/v1/summary').status_code==401
    assert client.get('/api/v1/summary',headers={'Authorization':'Bearer '+token}).status_code==503
    response=post(client,case,'/settings/restore')
    assert 'restored=1' in response.location
    assert client.get('/settings').status_code==200
    assert case.saved.read_bytes()==case.original
    case.unchanged_tracking()


def test_interrupted_settings_cannot_be_edited_before_restoration(page):
    client,case,_=page
    case.interrupt('after_config')
    original_request=case.pending.read_bytes()
    response=client.post('/settings',data={'HOLDING_DAYS':'13'},headers={'Origin':'http://localhost'})
    assert response.status_code==302 and 'apply_error=1' in response.location
    assert case.pending.read_bytes()==original_request
    body=client.get('/settings').text
    assert 'Restore Previous Settings' in body and 'before editing again' in body
    case.unchanged_tracking()


def test_busy_scan_retains_request_and_has_no_application_intent(page):
    client,case,_=page
    with state_writer_lock(case.source):response=post(client,case)
    assert 'apply_busy=1' in response.location
    assert case.pending.exists() and not case.marker.exists()
    assert case.saved.read_bytes()==case.original


@pytest.mark.parametrize('origin',[None,'http://other.invalid'])
def test_apply_requires_same_origin(page,origin):
    client,case,_=page
    response=client.post('/settings/apply',data={'request_sha256':case.digest},
        headers={} if origin is None else {'Origin':origin})
    assert response.status_code==403 and not case.marker.exists()
    assert case.saved.read_bytes()==case.original


def test_viewer_cannot_apply_or_restore(page,monkeypatch):
    client,case,_=page
    monkeypatch.setattr(web,'current_user',lambda:{'name':'Viewer','admin':False})
    assert post(client,case).status_code==403
    assert post(client,case,'/settings/restore').status_code==403
    assert not case.marker.exists()


def test_bearer_alone_cannot_apply_settings(page,monkeypatch):
    client,case,token=page
    monkeypatch.setattr(web,'current_user',lambda:None)
    response=client.post('/settings/apply',data={'request_sha256':case.digest},
        headers={'Origin':'http://localhost','Authorization':'Bearer '+token})
    assert response.status_code==302 and '/login' in response.location
    assert not case.marker.exists() and case.saved.read_bytes()==case.original


def edit_form(case, **changes):
    from config_store import KEYS,DEFAULTS,SECRETS
    values={key:str(case.values.get(key,DEFAULTS.get(key,''))) for key in KEYS}
    values.update({key:'' for key in SECRETS})
    values.update(settings_action='apply',**changes)
    return values


def test_one_apply_submission_preserves_tracking_and_does_not_queue_scan(page,monkeypatch):
    import json,run_control
    from unittest.mock import Mock
    client,case,_=page
    wake=Mock();monkeypatch.setattr(run_control,'wake_worker',wake)
    monkeypatch.setattr(web,'request_run',Mock(side_effect=AssertionError('No scan request')))
    response=client.post('/settings',data=edit_form(case,HOLDING_DAYS='13'),headers={'Origin':'http://localhost'})
    assert response.status_code==302 and 'applied=1' in response.location
    assert json.loads(case.saved.read_bytes())['HOLDING_DAYS']=='13'
    assert json.loads(case.saved.read_bytes())['private_extension']=={'clock':'keep-this'}
    assert not case.pending.exists() and not case.marker.exists()
    assert 'I UNDERSTAND' not in client.get('/settings').text
    wake.assert_called_once();case.unchanged_tracking()


def test_one_apply_busy_retains_exact_request_and_active_settings(page):
    import json
    client,case,_=page
    with state_writer_lock(case.source):
        response=client.post('/settings',data=edit_form(case,HOLDING_DAYS='13'),headers={'Origin':'http://localhost'})
    assert 'apply_busy=1' in response.location
    assert json.loads(case.pending.read_bytes())['requested_config']['HOLDING_DAYS']=='13'
    assert case.saved.read_bytes()==case.original and not case.marker.exists()
    case.unchanged_tracking()


def test_unchanged_form_can_apply_only_the_explicit_reviewed_request_digest(page):
    import json
    client,case,_=page
    response=client.post('/settings',data=edit_form(case),headers={'Origin':'http://localhost'})
    assert 'unchanged=1' in response.location and case.saved.read_bytes()==case.original
    response=client.post('/settings',data=edit_form(case,request_sha256=case.digest),headers={'Origin':'http://localhost'})
    assert 'applied=1' in response.location
    assert json.loads(case.saved.read_bytes())['HOLDING_DAYS']=='10'
    case.unchanged_tracking()


def test_concurrent_request_replacement_is_not_adopted_by_one_apply(page,monkeypatch):
    import json
    from app import sqlite_preview_settings as requests
    client,case,_=page
    original=requests.request_settings
    def replace_after_staging(**kwargs):
        result=original(**kwargs)
        newer=json.loads(case.saved.read_bytes());newer['HOLDING_DAYS']='19'
        original(config_path=case.saved,updated=newer,environment=case.values)
        return result
    monkeypatch.setattr(requests,'request_settings',replace_after_staging)
    response=client.post('/settings',data=edit_form(case,HOLDING_DAYS='13'),headers={'Origin':'http://localhost'})
    assert 'apply_error=1' in response.location
    assert json.loads(case.pending.read_bytes())['requested_config']['HOLDING_DAYS']=='19'
    assert case.saved.read_bytes()==case.original and not case.marker.exists()
    case.unchanged_tracking()


def test_interrupted_single_apply_still_requires_explicit_restore(page):
    client,case,_=page
    def stop(phase):
        if phase=='after_config':raise RuntimeError('private-never-expose')
    with patch.object(apply,'_boundary',stop):
        response=client.post('/settings',data=edit_form(case,HOLDING_DAYS='13'),headers={'Origin':'http://localhost'})
    assert 'apply_error=1' in response.location
    body=client.get('/settings').text
    assert 'Restore Previous Settings' in body and 'private-never-expose' not in body
    assert 'id="apply-settings-button"' not in body
    digest=apply.application_status(settings=case.values)['request_sha256']
    response=client.post('/settings/restore',data={'request_sha256':digest},headers={'Origin':'http://localhost'})
    assert 'restored=1' in response.location and case.saved.read_bytes()==case.original
    case.unchanged_tracking()


@pytest.mark.parametrize('key',['DRY_RUN','ALLOW_PERMANENT_DELETE','ALLOW_FILESYSTEM_DELETE','ALLOW_CROSS_FILESYSTEM_MOVES','ENABLE_SEASON_PRUNING'])
def test_single_apply_still_rejects_media_actions_without_typed_confirmation(page,key):
    client,case,_=page
    before=case.pending.read_bytes()
    value='false' if key=='DRY_RUN' else 'true'
    response=client.post('/settings',data=edit_form(case,**{key:value}),headers={'Origin':'http://localhost'})
    assert response.status_code==200 and 'cannot enable media actions' in response.text
    assert case.saved.read_bytes()==case.original and case.pending.read_bytes()==before
    case.unchanged_tracking()
