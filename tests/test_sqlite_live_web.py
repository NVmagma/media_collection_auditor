"""Live canary routes must not fall back to legacy settings or manual moves."""
from unittest.mock import Mock
import pytest
from test_integration_api import api, AUTH
from app import sqlite_backend_gate as gate
import web


@pytest.fixture
def live_client(api,monkeypatch):
    monkeypatch.setenv('AUDITOR_STATE_BACKEND','sqlite')
    monkeypatch.setattr(gate,'preview_release_enabled',lambda:False)
    monkeypatch.setattr(gate,'live_release_enabled',lambda:True)
    monkeypatch.setattr(web,'current_user',lambda:{'name':'Admin','admin':True})
    check=Mock(return_value={})
    monkeypatch.setattr(gate,'require_sqlite_read_authority',check)
    save=Mock(side_effect=AssertionError('No legacy configuration write'))
    monkeypatch.setattr(web,'save_config',save)
    return api[0],check,save


def test_live_settings_render_without_legacy_save_or_typing_confirmation(live_client):
    client,_,save=live_client
    response=client.get('/settings')
    assert response.status_code==200
    text=response.get_data(as_text=True)
    assert 'Live settings use reviewed application' in text
    assert 'Apply Requested Settings' in text
    assert 'Save Changes' not in text and 'I UNDERSTAND' not in text
    assert 'Fixed for this canary' in text
    save.assert_not_called()


def test_live_settings_submission_does_not_invalidate_binding(live_client):
    client,_,save=live_client
    assert client.post('/settings',data={'DRY_RUN':'true','ENABLE_TV':'false'},headers={'Origin':'http://localhost'}).status_code==200
    assert 'apply_error=1' in client.post('/settings/apply',headers={'Origin':'http://localhost'}).location
    assert 'apply_error=1' in client.post('/settings/restore',headers={'Origin':'http://localhost'}).location
    save.assert_not_called()


def test_live_manual_scan_never_queues_media_actions(live_client,monkeypatch):
    client,_,_=live_client
    legacy=Mock(side_effect=AssertionError('No legacy manual scan'))
    monkeypatch.setattr(web,'request_run',legacy)
    assert client.post('/api/run-now',headers={'Origin':'http://localhost'}).status_code==409
    legacy.assert_not_called()


def test_live_api_binding_failure_is_redacted(live_client):
    client,check,_=live_client
    check.side_effect=RuntimeError('private-path-token')
    response=client.get('/api/v1/summary',headers=AUTH)
    assert response.status_code==503
    assert 'private-path-token' not in response.get_data(as_text=True)
