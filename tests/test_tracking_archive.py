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
