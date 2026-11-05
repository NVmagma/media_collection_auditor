import json
from pathlib import Path
import re

import pytest
import web
from app import json_worker_service
from app.json_tracking_store import JsonTrackingStore
from app.json_worker_cycle import stage_paths
from test_integration_api import api


@pytest.fixture
def archive_page(api, monkeypatch, tmp_path):
    client, path = api
    state = {name: {} for name in ('first_seen', 'queued', 'keep_seen', 'in_removal', 'arr_sync_pending')}
    state['first_seen'] = {'Missing': '2020-01-01T00:00:00', 'Other': '2020-01-01T00:00:00'}
    state['extension'] = {'preserve': True}
    state['json_worker_control'] = dict(schema_version=1, last_started_at='2020-01-01T00:00:00+00:00',
                                        last_result='completed', trigger='manual', journal=None)
    path.write_text(json.dumps(state))
    settings = {'MEDIA_PATH': str(tmp_path), 'STATE_FILE': str(path)}
    monkeypatch.setattr(json_worker_service, 'settings_snapshot', lambda: settings)
    roots, _ = stage_paths(settings, 'Movies')
    for root in roots.values():
        (tmp_path / root).mkdir()
    monkeypatch.setattr(web, 'current_user', lambda: {'name': 'Admin', 'admin': True})

    def post(action, **fields):
        return client.post('/tracking-review/archive?library=Movies&title=Missing',
                           headers={'Origin': 'http://localhost'}, data={'action': action, **fields})
    return client, path, state, roots, post


def fingerprint(response):
    assert response.status_code == 200
    return re.search(r'name="fingerprint" value="([a-f0-9]+)"', response.text)[1]


def test_archives_only_reviewed_clock(archive_page):
    _, path, state, _, post = archive_page
    before = path.read_bytes()
    review = fingerprint(post('review'))
    assert path.read_bytes() == before
    assert post('archive', fingerprint=review).status_code == 200
    stored = json.loads(path.read_bytes())
    archived = stored.pop('archived_tracking_clocks')['Missing']
    assert archived['stage'] == 'Waiting'
    assert archived['timestamp'] == state['first_seen'].pop('Missing')
    assert stored == state
    assert post('archive', fingerprint=review).status_code == 409


@pytest.mark.parametrize("folder", ["Missing", "Ｍissing"])
def test_blocks_returning_folder_or_concurrent_worker(archive_page, folder):
    _, path, _, roots, post = archive_page
    before = path.read_bytes()
    review = fingerprint(post('review'))
    with JsonTrackingStore(path).session():
        # The HTTP request must not acquire a second audit lock.
        assert post('archive', fingerprint=review).status_code == 409
    (Path(roots['Keep']) / folder).mkdir()
    assert post('archive', fingerprint=review).status_code == 409
    assert path.read_bytes() == before


def test_requires_admin_origin_and_fresh_state(archive_page, monkeypatch):
    client, path, state, _, post = archive_page
    url = '/tracking-review/archive?library=Movies&title=Missing'
    assert client.post(url, data={'action': 'review'}).status_code == 403
    monkeypatch.setattr(web, 'current_user', lambda: {'name': 'Viewer', 'admin': False})
    assert post('review').status_code == 403
    monkeypatch.setattr(web, 'current_user', lambda: {'name': 'Admin', 'admin': True})
    review = fingerprint(post('review'))
    state['first_seen']['Missing'] = '2021-01-01T00:00:00'
    path.write_text(json.dumps(state))
    assert post('archive', fingerprint=review).status_code == 409
    assert json.loads(path.read_bytes()) == state


def test_pending_operation_blocks_review(archive_page):
    _, path, state, _, post = archive_page
    state['arr_sync_pending']['Other'] = {'stage': 'holding', 'root': '/media/Movies_hold'}
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    assert post('review').status_code == 409
    assert path.read_bytes() == before


def test_archive_history_filters_pages_and_preserves_state(archive_page, monkeypatch):
    client, path, state, _, _ = archive_page
    url = '/tracking-review/archive/history'
    assert 'No archived clocks' in client.get(url).text
    state['archived_tracking_clocks'] = {
        f'Movie {index:02}': {'stage': 'Holding', 'timestamp': '2020-01-01T01:02:03',
                             'archived_at': f'2026-01-{index:02}T02:00:00+02:00'}
        for index in range(1, 27)
    }
    state['archived_tracking_clocks']['TV/Example Show'] = {
        'stage': 'Keep', 'timestamp': '2020-02-01T01:02:03',
        'archived_at': '2026-01-27T00:00:00+00:00', 'private': 'hidden-value',
    }
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    response = client.get(url + '?library=Movies')
    assert response.status_code == 200
    assert '26 matching clocks · Page 1 of 2' in response.text
    assert response.text.index('Movie 26') < response.text.index('Movie 25')
    assert '2026-01-26 00:00:00' in response.text
    assert 'Movie 01' not in response.text and 'Example Show' not in response.text
    assert 'Movie 01' in client.get(url + '?library=Movies&page=2').text
    response = client.get(url + '?library=TV&q=example')
    assert 'Example Show' in response.text and '2020-02-01T01:02:03' in response.text
    assert 'hidden-value' not in response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.get(url + '?page=1&page=2').status_code == 400
    assert path.read_bytes() == before
    monkeypatch.setattr(web, 'current_user', lambda: {'name': 'Viewer', 'admin': False})
    assert client.get(url).status_code == 403


def test_invalid_archive_is_unavailable(archive_page):
    client, path, state, _, _ = archive_page
    state['archived_tracking_clocks'] = {'Private malformed entry': {'stage': 'Keep'}}
    path.write_text(json.dumps(state))
    response = client.get('/tracking-review/archive/history')
    assert response.status_code == 503
    assert 'Private malformed entry' not in response.text
