"""API-only deployments never start the worker or invent coordinator activity."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

os.environ.setdefault('WEB_SESSION_SECRET', 'test-only-api-service-secret')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import web
from integration_api import read_only_service_enabled
from tests.test_docker_runtime_context import context

TOKEN = 'disposable_service_token_01234567890123456789'
AUTH = {'Authorization': 'Bearer ' + TOKEN}


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv('READ_ONLY_API_SERVICE', 'true')
    monkeypatch.setenv('INTEGRATION_API_TOKEN', TOKEN)
    state = tmp_path / 'state.json'
    state.write_text('{"queued":{"Private title":"2024-01-01"}}')
    monkeypatch.setattr(web, 'STATE_FILE', str(state))
    monkeypatch.setattr(web, 'current_user', lambda: pytest.fail('No browser authentication'))
    monkeypatch.setattr(web, 'snapshot', lambda: pytest.fail('No separate-process coordinator claim'))
    return web.app.test_client(), state


def test_api_only_summary_and_health_are_read_only(service):
    client, state = service
    before = state.read_bytes()
    response = client.get('/api/v1/summary', headers=AUTH)
    assert response.status_code == 200
    assert response.json['tracking_counts']['holding'] == 1
    assert response.json['storage_authority'] == 'json'
    assert 'Private title' not in response.text
    assert state.read_bytes() == before
    assert client.get('/health').status_code == 200
    assert client.get('/api/v1/summary').status_code == 401


def test_sidecar_coordinator_is_unknown_not_idle(service):
    client, _ = service
    response = client.get('/api/v1/audit-status', headers=AUTH)
    assert response.status_code == 503
    assert response.json['running'] is None
    assert response.json['queued'] is None
    assert response.json['last_result'] is None
    assert response.json['source'] == 'coordinator_unavailable_in_read_only_service'


@pytest.mark.parametrize('route,method', [('/', 'GET'), ('/login', 'POST'),
    ('/logout', 'POST'), ('/settings', 'GET'), ('/api/run-now', 'POST'),
    ('/api/rescue', 'POST'), ('/api/test-connection/jellyfin', 'POST'),
    ('/api/poster', 'GET'), ('/static/example.png', 'GET')])
def test_browser_action_and_extra_read_routes_are_disabled(service, route, method):
    client, _ = service
    assert client.open(route, method=method, headers=AUTH).status_code == 404


@pytest.mark.parametrize('value,expected', [('true', True), ('TRUE', True), ('false', False)])
def test_service_mode_explicit_values(monkeypatch, value, expected):
    monkeypatch.setenv('READ_ONLY_API_SERVICE', value)
    assert read_only_service_enabled() is expected


@pytest.mark.parametrize('value', ['', 'tru', '1'])
def test_invalid_service_selection_never_falls_back_to_worker(monkeypatch, value):
    monkeypatch.setenv('READ_ONLY_API_SERVICE', value)
    with pytest.raises(RuntimeError):
        read_only_service_enabled()


def test_actual_image_entrypoint_exits_before_importing_worker_or_writing_session_key(tmp_path):
    runtime = context(tmp_path)
    (runtime / 'collection_auditor.py').write_text('raise AssertionError("Worker imported")\n')
    env = {'PYTHONPATH': str(runtime), 'READ_ONLY_API_SERVICE': 'true',
           'WEB_SESSION_KEY_FILE': str(runtime / 'must-not-create.key'),
           'EXPERIMENTAL_SQLITE_RECOVERY_VIEW': 'true',
           'EXPERIMENTAL_SQLITE_RECOVERY_DB': str(runtime / 'must-not-open.db')}
    child = '''
import runpy
from flask import Flask
Flask.run = lambda *a, **kw: print("API_WEB_STARTED")
runpy.run_path("main.py", run_name="__main__")
'''
    result = subprocess.run([sys.executable, '-B', '-c', child], env=env,
                            cwd=runtime, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'API_WEB_STARTED'
    assert not (runtime / 'must-not-create.key').exists()
    assert not (runtime / 'must-not-open.db').exists()


def test_read_only_service_smoke_command(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'scripts/integration_api_smoke.py'
    result = subprocess.run([sys.executable, '-B', str(script), '--read-only-service'],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['read_only_service'] is True
