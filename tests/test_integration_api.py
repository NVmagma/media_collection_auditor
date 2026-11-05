"""Dedicated API auth cannot confer dashboard or action permissions."""
import json
import os
from pathlib import Path
import sys

import pytest

os.environ.setdefault('WEB_SESSION_SECRET', 'test-only-integration-session-secret')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import web

TOKEN = 'disposable_integration_token_0123456789'
AUTH = {'Authorization': 'Bearer ' + TOKEN}


@pytest.fixture
def api(tmp_path, monkeypatch):
    state = tmp_path / 'state.json'
    state.write_text('{"queued":{"private-title":"2024-01-01"}}')
    monkeypatch.setattr(web, 'STATE_FILE', str(state))
    monkeypatch.setenv('INTEGRATION_API_TOKEN', TOKEN)
    monkeypatch.setattr(web, 'current_user', lambda: None)
    monkeypatch.setattr(web.requests.sessions.Session, 'request',
                        lambda *a, **kw: pytest.fail('No network collection permitted'))
    return web.app.test_client(), state


@pytest.mark.parametrize('token', ['', 'short', 'x' * 257, 'secret with spaces' * 3, 'é' * 32])
def test_disabled_or_invalid_configuration_does_not_read_state(api, monkeypatch, token):
    client, _ = api
    monkeypatch.setenv('INTEGRATION_API_TOKEN', token)
    monkeypatch.setattr(web, 'read_tracking_status', lambda *a: pytest.fail('Auth first'))
    response = client.get('/api/v1/summary', headers=AUTH)
    assert response.status_code == 404
    assert response.json == {'status': 'disabled'}
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('header', ['', 'Basic ' + TOKEN, 'Bearer wrong',
    'Bearer ' + 'x' * 40, 'Bearer ' + TOKEN + ',Bearer ' + TOKEN, 'Bearer ' + 'é' * 40])
def test_authentication_precedes_all_reads(api, monkeypatch, header):
    client, _ = api
    monkeypatch.setattr(web, 'read_tracking_status', lambda *a: pytest.fail('Auth first'))
    response = client.get('/api/v1/summary', headers={'Authorization': header})
    assert response.status_code == 401
    assert response.json == {'status': 'unauthorized'}
    assert response.headers['WWW-Authenticate'] == 'Bearer'
    assert response.headers['Cache-Control'] == 'no-store'


def test_browser_session_and_query_token_are_not_api_credentials(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(web, 'current_user', lambda: {'admin': True})
    assert client.get('/api/v1/summary?token=' + TOKEN).status_code == 401


def test_unsupported_backend_selection_never_falls_back_to_json_and_leaves_state_unchanged(api, monkeypatch):
    client, path = api
    raw = path.read_bytes()
    monkeypatch.setenv('AUDITOR_STATE_BACKEND', 'unsupported')
    response = client.get('/api/v1/summary?state=/some/other/file', headers=AUTH)
    assert response.status_code == 503
    assert response.json['tracking_counts'] is None
    assert response.json['storage_authority'] == 'unavailable'
    assert response.json['freshness_verified'] is False
    assert response.json['production_authorized'] is False
    assert 'private-title' not in response.text
    assert TOKEN not in response.text
    assert str(path) not in response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Vary'] == 'Authorization'
    assert path.read_bytes() == raw


def test_missing_state_returns_503_not_healthy_empty(api):
    client, path = api
    path.unlink()
    response = client.get('/api/v1/summary', headers=AUTH)
    assert response.status_code == 503
    assert response.json['tracking_counts'] is None
    assert not path.exists()


def test_token_rotation_revokes_old_token(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv('INTEGRATION_API_TOKEN', 'replacement_disposable_token_0123456789')
    assert client.get('/api/v1/summary', headers=AUTH).status_code == 401
    assert client.get('/api/v1/summary', headers={
        'Authorization': 'Bearer replacement_disposable_token_0123456789'}).status_code == 200


@pytest.mark.parametrize('path', ['/api/run-now', '/api/rescue', '/api/test-connection/jellyfin'])
def test_integration_token_cannot_authorize_actions(api, path):
    client, _ = api
    assert client.post(path, headers=AUTH, json={}).status_code == 401


def test_summary_cannot_be_posted_and_token_cannot_open_dashboard(api):
    client, _ = api
    assert client.post('/api/v1/summary', headers=AUTH).status_code in (401, 405)
    assert client.get('/', headers=AUTH).status_code == 302
    assert client.get('/health').status_code == 200


def test_corrupt_state_is_redacted_and_head_has_no_body(api):
    client, path = api
    path.write_text('{"queued":{"private-title":"invalid"}}')
    response = client.get('/api/v1/summary', headers=AUTH)
    assert response.status_code == 503
    assert response.json['status'] == 'unavailable'
    assert 'private-title' not in response.text
    head = client.head('/api/v1/summary', headers=AUTH)
    assert head.status_code == 503
    assert head.data == b''


def test_disposable_smoke_command(tmp_path):
    import subprocess
    result = subprocess.run([sys.executable, '-B', str(
        Path(__file__).resolve().parents[1] / 'scripts/integration_api_smoke.py')],
        cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'disposable_api_smoke_passed'


@pytest.mark.parametrize('headers,code', [({}, 401), (AUTH, 200)])
def test_audit_status_auth_and_redaction(api, monkeypatch, headers, code):
    client, _ = api
    calls = []

    def status():
        calls.append(True)
        return {'running': True, 'queued': False, 'rescuing': False,
                'last_result': '/private/error', 'error': 'secret-token',
                'last_started': '2026-01-01T01:00:00+01:00',
                'last_finished': 'not-a-date-secret', 'next_run': None}

    monkeypatch.setattr(web, 'snapshot', status)
    response = client.get('/api/v1/audit-status', headers=headers)
    assert response.status_code == code
    assert len(calls) == (1 if code == 200 else 0)
    assert response.headers['Cache-Control'] == 'no-store'
    if code == 200:
        assert response.json['running'] is True
        assert response.json['last_started'] == '2026-01-01T00:00:00+00:00'
        assert response.json['last_finished'] is None
        assert response.json['last_result'] is None
        assert 'private' not in response.text
        assert 'secret' not in response.text


@pytest.mark.parametrize('value', [None, {}, {'running': 'false', 'queued': False, 'rescuing': False}])
def test_unknown_coordinator_state_is_not_idle(api, monkeypatch, value):
    client, _ = api
    monkeypatch.setattr(web, 'snapshot', lambda: value)
    response = client.get('/api/v1/audit-status', headers=AUTH)
    assert response.status_code == 503
    assert response.json['running'] is None


def test_coordinator_read_error_is_redacted(api, monkeypatch):
    client, _ = api

    def failure():
        raise UnicodeError('/private/history secret')

    monkeypatch.setattr(web, 'snapshot', failure)
    response = client.get('/api/v1/audit-status', headers=AUTH)
    assert response.status_code == 503
    assert 'secret' not in response.text


def test_audit_status_disabled_and_browser_session_not_sufficient(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(web, 'current_user', lambda: {'admin': True})
    monkeypatch.setattr(web, 'snapshot', lambda: pytest.fail('No unauthorized reads'))
    assert client.get('/api/v1/audit-status').status_code == 401
    monkeypatch.delenv('INTEGRATION_API_TOKEN')
    assert client.get('/api/v1/audit-status', headers=AUTH).status_code == 404


def test_unsupported_backend_audit_status_never_reads_json_coordinator_history(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv('AUDITOR_STATE_BACKEND', 'unsupported')
    monkeypatch.setattr(web, 'snapshot', lambda: pytest.fail('No JSON coordinator fallback'))
    response = client.get('/api/v1/audit-status', headers=AUTH)
    assert response.status_code == 503
    assert response.json['storage_authority'] == 'unavailable'
    assert response.json['last_result'] is None and response.json['running'] is None


def test_unsupported_backend_manual_run_does_not_queue_legacy_worker(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv('AUDITOR_STATE_BACKEND', 'unsupported')
    monkeypatch.setattr(web, 'current_user', lambda: {'admin': True})
    monkeypatch.setattr(web, 'admin_authorized', lambda: True)
    monkeypatch.setattr(web, 'request_run', lambda: pytest.fail('Daily-only backend cannot queue legacy worker'))
    response = client.post('/api/run-now', headers={'Origin': 'http://localhost'})
    assert response.status_code == 409
    assert 'configuration' in response.json['message']
