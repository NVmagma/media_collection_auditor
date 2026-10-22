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


def test_summary_is_redacted_json_only_and_leaves_state_unchanged(api, monkeypatch):
    client, path = api
    raw = path.read_bytes()
    monkeypatch.setenv('AUDITOR_STATE_BACKEND', 'sqlite')
    response = client.get('/api/v1/summary?state=/some/other/file', headers=AUTH)
    assert response.status_code == 200
    assert response.json['tracking_counts']['holding'] == 1
    assert response.json['storage_authority'] == 'json'
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
