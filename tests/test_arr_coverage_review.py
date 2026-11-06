from unittest.mock import Mock

import web
from app import arr_catalog, json_worker_service
from test_integration_api import api


def test_explicit_admin_check_uses_saved_aliases_and_one_catalog(api, monkeypatch):
    client, state_file = api
    state_before = state_file.read_bytes()
    settings = {
        'MEDIA_PATH': '/media',
        'ENABLE_MOVIES': 'true',
        'ENABLE_TV': 'true',
        'RADARR_URL': 'http://fixture.invalid',
        'RADARR_API_KEY': 'fixture-secret',
        'RADARR_APP_HOLDING_PATH': '/arr/held',
    }
    monkeypatch.setattr(json_worker_service, 'settings_snapshot', lambda: settings)
    stages = {'Waiting': [{'title': 'Unmatched'}, {'title': 'Wrong path'}],
              'Holding': [{'title': 'Exact'}, {'title': 'Duplicate'}],
              'Keep': [], 'Removal': []}
    inventory = Mock(return_value=(stages, []))
    monkeypatch.setattr(web, 'filesystem_stages', inventory)
    fetch = Mock(return_value=[
        {'id': 1, 'path': '/arr/held/Exact/', 'monitored': False},
        {'id': 2, 'path': '/arr/held/Duplicate', 'monitored': True},
        {'id': 3, 'path': '/arr/held/Duplicate', 'monitored': False},
        {'id': 4, 'path': '/private/WRONG PATH', 'monitored': True},
    ])
    transport = Mock(return_value=fetch)
    monkeypatch.setattr(arr_catalog, 'ArrCatalogGET', transport)
    route = '/tracking-review/arr'
    assert client.get(route).status_code == 302
    monkeypatch.setattr(web, 'current_user', lambda: {'name': 'Viewer', 'admin': False})
    assert client.get(route).status_code == 403
    monkeypatch.setattr(web, 'current_user', lambda: {'name': 'Admin', 'admin': True})
    assert client.get(route).status_code == 200
    assert client.post(route, data={'library': 'Movies'}).status_code == 403
    transport.assert_not_called()

    response = client.post(route, data={'library': 'Movies', 'url': 'http://other.invalid'},
                           headers={'Origin': 'http://localhost'})
    assert response.status_code == 200
    assert '4 folders compared' in response.text
    for label in ('Exact Arr path', 'Similar folder name at a different path',
                  'Multiple matching Arr records', 'No matching Arr folder name'):
        assert label + ' · 1' in response.text
    assert 'fixture-secret' not in response.text and '/private/' not in response.text
    transport.assert_called_once_with(service='radarr', base_url='http://fixture.invalid',
                                      token='fixture-secret')
    fetch.assert_called_once_with()
    assert inventory.call_count == 2
    assert inventory.call_args.args[1]['ENABLE_TV'] == 'false'
    assert state_file.read_bytes() == state_before

    inventory.side_effect = [(stages, []), ({}, [])]
    response = client.post(route, data={'library': 'Movies'}, headers={'Origin': 'http://localhost'})
    assert response.status_code == 503 and 'Coverage is unknown' in response.text
    assert 'folders compared' not in response.text
