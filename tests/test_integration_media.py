"""Exact presentation matching never conveys lifecycle or credential authority."""
import json
import pytest
from app.integration_status import collect_widget_media_index, widget_media_urls
from test_integration_api import api, AUTH

UID = 'a' * 32
ITEM = 'b' * 32
OTHER = 'c' * 32
BASE = 'http://jellyfin.example:8096/jellyfin'


def movie(item_id=ITEM, path='/private/Fixture (2024)/movie.mkv', **extra):
    return dict(Id=item_id, Path=path, Type='Movie', ImageTags={'Primary': 'tag'}, **extra)


def catalog(items, **kwargs):
    return {'Items': items, 'TotalRecordCount': len(items), **kwargs}


def index_for(items):
    def fetch(path, params):
        return [{'Id': UID}] if path == '/Users' else catalog(items)
    return collect_widget_media_index(fetch, 'Movie')


def test_exact_match_returns_only_credential_free_urls():
    result = widget_media_urls({'title': 'Fixture (2024)'}, index_for([movie()]), BASE)
    assert result['match_status'] == 'matched'
    assert result['poster_url'] == BASE + '/Items/' + ITEM + '/Images/Primary?maxWidth=160&quality=80'
    assert result['jellyfin_url'] == BASE + '/web/index.html#!/details?id=' + ITEM
    assert '/private' not in json.dumps(result)
    assert widget_media_urls({'title': 'Fixture'}, index_for([movie()]), BASE)['match_status'] == 'unmatched'


def test_duplicates_are_ambiguous_not_first_wins():
    index = index_for([movie(), movie(OTHER, '/other/Fixture (2024)/movie.mkv')])
    result = widget_media_urls({'title': 'Fixture (2024)'}, index, BASE)
    assert result == {'match_status': 'ambiguous', 'poster_url': None, 'jellyfin_url': None}


def test_same_item_seen_by_multiple_users_is_one_identity():
    def fetch(path, params):
        return [{'Id': UID}, {'Id': OTHER}] if path == '/Users' else catalog([movie()])
    index = collect_widget_media_index(fetch, 'Movie')
    assert widget_media_urls({'title': 'Fixture (2024)'}, index, BASE)['match_status'] == 'matched'


@pytest.mark.parametrize('base', ['javascript:alert(1)', '//evil.example',
    'http://user:secret@jellyfin.example', 'http://jellyfin.example?api_key=secret',
    'http://jellyfin.example/#token', 'http://jellyfin.example:bad',
    'http://jellyfin.example/../private', 'http://jellyfin.example\\@evil.example',
    'http://jellyfin.example/secret\n', 'http://%65vil.example', ''])
def test_unsafe_public_url_never_returned(base):
    result = widget_media_urls({'title': 'Fixture (2024)'}, index_for([movie()]), base)
    assert result['jellyfin_url'] is None
    assert result['poster_url'] is None


@pytest.mark.parametrize('data', [None, [], {'Items': [], 'TotalRecordCount': 1},
    {'Items': [movie()], 'TotalRecordCount': True}, catalog([movie()], StartIndex=1),
    catalog([movie(), movie()]), catalog([dict(movie(), Type='Series')]),
    catalog([dict(movie(), Id='../../secret')])])
def test_partial_or_invalid_catalog_is_rejected(data):
    def fetch(path, params):
        return [{'Id': UID}] if path == '/Users' else data
    with pytest.raises(ValueError):
        collect_widget_media_index(fetch, 'Movie')


def test_pagination_completes_before_matching():
    calls = []
    def fetch(path, params):
        if path == '/Users':
            return [{'Id': UID}]
        calls.append(params['StartIndex'])
        start = params['StartIndex']
        return {'Items': [movie(f'{n:032x}', f'/private/Movie {n}/film.mkv')
                          for n in range(start, min(start + 100, 101))],
                'TotalRecordCount': 101, 'StartIndex': start}
    index = collect_widget_media_index(fetch, 'Movie')
    assert calls == [0, 100]
    assert widget_media_urls({'title': 'Movie 100'}, index, BASE)['match_status'] == 'matched'


def test_missing_image_keeps_verified_navigation():
    item = movie()
    item.pop('ImageTags')
    result = widget_media_urls({'title': 'Fixture (2024)'}, index_for([item]), BASE)
    assert result['match_status'] == 'matched'
    assert result['poster_url'] is None
    assert result['jellyfin_url']


def test_default_disabled_does_not_contact_jellyfin(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv('INTEGRATION_API_TITLE_DETAILS', 'true')
    monkeypatch.delenv('INTEGRATION_API_MEDIA', raising=False)
    monkeypatch.setattr('web.load_config', lambda: pytest.fail('No config/network reads when disabled'))
    response = client.get('/api/v1/titles/oldest-waiting', headers=AUTH)
    assert response.status_code == 200
    assert response.json['media_lookup_status'] == 'disabled'


def test_metadata_failure_preserves_tracking_list(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv('INTEGRATION_API_TITLE_DETAILS', 'true')
    monkeypatch.setenv('INTEGRATION_API_MEDIA', 'true')
    monkeypatch.setenv('JELLYFIN_PUBLIC_URL', BASE)
    monkeypatch.setattr('web.load_config', lambda: {})
    def fail(*args):
        raise ValueError('secret path and token must not escape')
    monkeypatch.setattr('web._widget_media_index', fail)
    response = client.get('/api/v1/titles/leaving-soon', headers=AUTH)
    assert response.status_code == 200
    assert len(response.json['items']) == 1
    assert response.json['media_lookup_status'] == 'unavailable'
    assert response.json['items'][0]['poster_url'] is None
    assert 'secret path' not in response.text


def test_series_folder_and_boxsets_cannot_be_confused():
    def fetch(path, params):
        if path == '/Users':
            return [{'Id': UID}]
        return catalog([{'Id': ITEM, 'Type': 'Series', 'Path': '/tv/Fixture', 'ImageTags': {}},
                        {'Id': OTHER, 'Type': 'BoxSet'}])
    index = collect_widget_media_index(fetch, 'Series')
    assert widget_media_urls({'title': 'Fixture'}, index, BASE)['match_status'] == 'matched'


def test_complete_empty_catalog_is_unmatched():
    assert widget_media_urls({'title': 'Fixture'}, index_for([]), BASE)['match_status'] == 'unmatched'


def test_opt_in_route_uses_saved_private_credentials_but_public_links(api, monkeypatch):
    client, path = api
    path.write_text('{"first_seen":{"Fixture (2024)":"2024-01-01"}}')
    monkeypatch.setenv('INTEGRATION_API_TITLE_DETAILS', 'true')
    monkeypatch.setenv('INTEGRATION_API_MEDIA', 'true')
    monkeypatch.setenv('JELLYFIN_PUBLIC_URL', BASE)
    monkeypatch.setenv('JELLYFIN_API_TOKEN', 'wrong-env-token')
    monkeypatch.setattr('web.load_config', lambda: {'JELLYFIN_HOST_URL': 'http://private:8096',
                                                  'JELLYFIN_API_TOKEN': 'private-test-key'})
    monkeypatch.setattr('web._WIDGET_MEDIA_CACHE', {})
    calls = []
    class Response:
        status_code = 200
        def __init__(self, data): self.data = data
        def json(self): return self.data
    def get(url, **kwargs):
        calls.append((url, kwargs))
        assert kwargs['allow_redirects'] is False
        assert kwargs['headers']['X-Emby-Token'] == 'private-test-key'
        return Response([{'Id': UID}] if url.endswith('/Users') else catalog([movie()]))
    monkeypatch.setattr('web.requests.get', get)
    url = '/api/v1/titles/oldest-waiting'
    report = client.get(url, headers=AUTH).json
    assert report['items'][0]['poster_url'].startswith(BASE + '/Items/')
    assert report['items'][0]['jellyfin_url'].startswith(BASE + '/web/')
    assert report['items'][0]['match_status'] == 'matched'
    assert len(calls) == 2
    assert 'private-test-key' not in json.dumps(report)
    assert 'http://private' not in json.dumps(report)
    client.get(url, headers=AUTH)
    assert len(calls) == 2  # Complete catalog reused, not a scan per row.
    import web
    for key, (_, index) in list(web._WIDGET_MEDIA_CACHE.items()):
        web._WIDGET_MEDIA_CACHE[key] = (web.time.monotonic() - 301, index)
    def offline(*args, **kwargs):
        raise web.requests.ConnectionError('secret')
    monkeypatch.setattr('web.requests.get', offline)
    failed = client.get(url, headers=AUTH).json
    assert failed['items'][0]['poster_url'] is None
    assert failed['items'][0]['jellyfin_url'] is None
    assert failed['media_lookup_status'] == 'unavailable'
    assert failed['items'][0]['title'] == 'Fixture (2024)'


def test_missing_public_base_performs_no_collection(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv('INTEGRATION_API_TITLE_DETAILS', 'true')
    monkeypatch.setenv('INTEGRATION_API_MEDIA', 'true')
    monkeypatch.delenv('JELLYFIN_PUBLIC_URL', raising=False)
    monkeypatch.setattr('web.load_config', lambda: {})
    monkeypatch.setattr('web._widget_media_index', lambda *a: pytest.fail('No public base'))
    report = client.get('/api/v1/titles/leaving-soon', headers=AUTH).json
    assert report['items'][0]['poster_url'] is None
    assert report['media_lookup_status'] == 'unavailable'


def test_saved_settings_url_is_default_browser_destination(api, monkeypatch):
    client, path = api
    path.write_text('{"first_seen":{"Fixture (2024)":"2024-01-01"}}')
    monkeypatch.setenv('INTEGRATION_API_TITLE_DETAILS', 'true')
    monkeypatch.setenv('INTEGRATION_API_MEDIA', 'true')
    monkeypatch.delenv('JELLYFIN_PUBLIC_URL', raising=False)
    monkeypatch.setenv('JELLYFIN_HOST_URL', 'http://wrong-environment:8096')
    monkeypatch.setattr('web.load_config', lambda: {'JELLYFIN_HOST_URL': 'http://10.0.0.10:8086',
                                                  'JELLYFIN_API_TOKEN': 'server-only-test-key'})
    seen = []
    def lookup(base, token, media_type):
        seen.append((base, token, media_type))
        return index_for([movie()]), 'collected'
    monkeypatch.setattr('web._widget_media_index', lookup)
    response = client.get('/api/v1/titles/oldest-waiting', headers=AUTH)
    assert seen == [('http://10.0.0.10:8086', 'server-only-test-key', 'Movie')]
    assert response.json['items'][0]['poster_url'].startswith('http://10.0.0.10:8086/Items/')
    assert response.json['items'][0]['jellyfin_url'].startswith('http://10.0.0.10:8086/web/')
    assert 'server-only-test-key' not in response.text


@pytest.mark.parametrize('base', ['http://jellyfin.example?', 'http://jellyfin.example#'])
def test_even_empty_url_delimiters_are_rejected(base):
    assert widget_media_urls({'title': 'Fixture (2024)'}, index_for([movie()]), base)['poster_url'] is None


def test_relative_catalog_paths_are_rejected():
    with pytest.raises(ValueError):
        index_for([movie(path='Fixture (2024)/film.mkv')])


def test_windows_paths_are_supported_without_exposing_them():
    result = widget_media_urls({'title': 'Fixture (2024)'},
                               index_for([movie(path=r'C:\Media\Fixture (2024)\film.mkv')]), BASE)
    assert result['match_status'] == 'matched'
    assert 'Media' not in json.dumps(result)


def test_widget_catalog_requests_individual_movies_in_grouped_libraries():
    calls = []
    def fetch(path, params):
        if path == '/Users': return [{'Id': UID}]
        calls.append(params)
        return catalog([movie()] if params.get('CollapseBoxSetItems') == 'false' else [])
    index = collect_widget_media_index(fetch, 'Movie')
    assert widget_media_urls({'title':'Fixture (2024)'}, index, BASE)['match_status'] == 'matched'
    assert calls and all(params['CollapseBoxSetItems'] == 'false' for params in calls)
