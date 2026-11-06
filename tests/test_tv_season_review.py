from pathlib import Path

import pytest
import web
from app import json_worker_service, tv_season_review
from app.json_worker_cycle import stage_paths
from test_integration_api import api


@pytest.fixture
def season_case(api, tmp_path, monkeypatch):
    client, state_file = api
    settings = {'MEDIA_PATH': str(tmp_path), 'ENABLE_TV': 'true'}
    roots, _ = stage_paths(settings, 'TV')
    for root in roots.values():
        Path(root).mkdir()
    show = Path(roots['Waiting']) / 'Example'
    for label in ('Season 0', 'Season 01', 'Season 3', 'Season 9'):
        (show / label).mkdir(parents=True)
    for label in ('Season 0', 'Season 01', 'Season 3'):
        (show / label / 'episode.mkv').write_bytes(b'disposable fixture')
    tags = ['one-season']

    def jellyfin(path, params):
        if path == '/Users':
            return [{'Id': 'viewer'}]
        return {'TotalRecordCount': 1, 'Items': [{'Id': 'show', 'Type': 'Series', 'Path': str(show),
                'Tags': tags, 'UserData': {'Played': False, 'PlayCount': 0, 'IsFavorite': True}}]}

    rows = [{'id': 1, 'monitored': True, 'path': str(show)}]
    monkeypatch.setattr(tv_season_review, 'ArrCatalogGET', lambda **kwargs: lambda: rows)
    monkeypatch.setattr(tv_season_review, 'ScheduledJellyfinGET', lambda **kwargs: jellyfin)
    monkeypatch.setattr(json_worker_service, 'settings_snapshot', lambda: settings)
    return client, state_file, show, tags, rows


def test_explicit_review_uses_local_seasons_and_verified_tags(season_case, monkeypatch):
    client, state_file, show, tags, _ = season_case
    url = '/tracking-review/tv-seasons'
    before = state_file.read_bytes()
    assert client.get(url).status_code == 302
    monkeypatch.setattr(web, 'current_user', lambda: {'name': 'Viewer', 'admin': False})
    assert client.get(url).status_code == 403
    monkeypatch.setattr(web, 'current_user', lambda: {'name': 'Admin', 'admin': True})
    assert client.post(url, data={'title': 'Example'}).status_code == 403
    origin = {'Origin': 'http://localhost'}
    response = client.post(url, data={'title': 'Example'}, headers=origin)
    assert response.status_code == 200
    assert 'Latest regular season with video files: 3.' in response.text
    assert 'TV Leaving Soon: 1.' in response.text
    tags.append('keep-all')
    assert 'No seasons selected' in client.post(url, data={'title': 'Example'}, headers=origin).text
    assert (show / 'Season 01' / 'episode.mkv').is_file()
    assert state_file.read_bytes() == before


def test_conflicting_sonarr_path_and_ambiguous_season_block(season_case, monkeypatch):
    client, _, show, _, rows = season_case
    monkeypatch.setattr(web, 'current_user', lambda: {'name': 'Admin', 'admin': True})
    def post():
        return client.post('/tracking-review/tv-seasons', data={'title': 'Example'},
                           headers={'Origin': 'http://localhost'})
    rows[0]['path'] = '/different/Example'
    assert post().status_code == 409
    rows[0]['path'] = str(show)
    (show / 'Season 1').mkdir()
    assert post().status_code == 409
