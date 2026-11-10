"""Readiness and browser setup never confer write or credential authority."""
from tests.test_integration_api import api, AUTH, TOKEN
import web
import pytest


def test_readiness_auth_first_no_network_or_private_projection(api, monkeypatch):
    client, state = api
    raw = state.read_bytes()
    assert client.get('/api/v1/readiness').status_code == 401
    response = client.get('/api/v1/readiness', headers=AUTH)
    assert response.status_code == 200
    assert response.json['tracking_available'] is True
    assert response.json['freshness_verified'] is False
    assert response.json['media_actions_authorized'] is False
    assert '/api/v1/readiness' in response.json['routes']
    assert TOKEN not in response.text and 'private-title' not in response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert state.read_bytes() == raw
    state.unlink()
    assert client.get('/api/v1/readiness', headers=AUTH).status_code == 503
    assert not state.exists()


def test_unknown_route_distinct_from_auth(api):
    client, _ = api
    assert client.get('/api/v1/not-a-route').status_code == 401
    response = client.get('/api/v1/not-a-route', headers=AUTH)
    assert response.status_code == 404 and response.json['status'] == 'route_not_found'
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('user,status', [(None,302), ({'admin':False},403)])
def test_setup_requires_browser_administrator(api, monkeypatch, user, status):
    client, _ = api
    monkeypatch.setattr(web, 'current_user', lambda:user)
    assert client.get('/integrations', headers=AUTH).status_code == status


def test_setup_is_private_read_only_and_explicit(api, monkeypatch):
    client, state = api
    monkeypatch.setattr(web, 'current_user', lambda:{'admin':True,'name':'Tester'})
    before = state.read_bytes()
    response = client.get('/integrations')
    assert response.status_code == 200
    assert TOKEN not in response.text and str(state) not in response.text
    assert 'Literal' in response.text and 'Movies' in response.text and 'TV' in response.text
    assert 'Settings → Integrations' in response.text and 'No container restart' in response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.post('/integrations', headers=AUTH).status_code == 405
    assert state.read_bytes() == before




def test_sidecar_readiness_has_no_coordinator_claim(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv('READ_ONLY_API_SERVICE','true')
    monkeypatch.setattr(web, 'current_user', lambda:pytest.fail('No browser session'))
    response = client.get('/api/v1/readiness', headers=AUTH)
    assert response.status_code == 200
    assert response.json['coordinator_scope'] == 'unavailable'
    assert client.get('/integrations', headers=AUTH).status_code == 404


def test_disposable_setup_page_has_no_production_binding_or_actions(monkeypatch):
    from scripts.dashboard_workspace_server import create_preview_app
    monkeypatch.setattr(web, '_integration_readiness', lambda:pytest.fail('Synthetic data only'))
    client = create_preview_app().test_client()
    response = client.get('/integrations')
    assert response.status_code == 200
    assert 'Synthetic integration setup' in response.text
    assert client.get('/static/integrations.js').status_code == 200
    assert client.post('/integrations').status_code == 405
    assert client.post('/settings/apply').status_code == 405


def test_readiness_rotated_token_and_query_credentials(api, monkeypatch):
    client, _ = api
    replacement = 'replacement_disposable_token_0123456789'
    monkeypatch.setenv('INTEGRATION_API_TOKEN', replacement)
    assert client.get('/api/v1/readiness', headers=AUTH).status_code == 401
    assert client.get('/api/v1/readiness?token='+replacement).status_code == 401
    assert client.get('/api/v1/readiness', headers={'Authorization':'Bearer '+replacement}).status_code == 200
