"""Check Arr IDs and paths before preparing updates. These tests only read catalogs."""
from copy import deepcopy
from types import SimpleNamespace as Object
from unittest.mock import patch

import pytest

from app.arr_catalog import ArrCatalogError, ArrCatalogGET, configured_arr_queue_resolver
def scheduled_worker_from_settings(settings):
    from app.json_worker_cycle import stage_paths
    return Object(libraries=[Object(name=name,jellyfin_type=kind,roots=tuple(stage_paths(settings,name)[0].items()))
        for name,kind in (('Movies','Movie'),('TV','Series'))])
import app.arr_catalog as module


def inputs():
    settings = {'DAILY_RUN_TIME': '02:00', 'DAILY_RUN_TIMEZONE': 'UTC',
        'ENABLE_TV': 'true', 'RADARR_URL': 'http://fixture-radarr', 'RADARR_API_KEY': 'movie-key',
        'SONARR_URL': 'http://fixture-sonarr', 'SONARR_API_KEY': 'tv-key',
        'RADARR_APP_HOLDING_PATH': '/arr-view/Movies_hold', 'SONARR_APP_KEEP_PATH': '/arr-view/TV_keep'}
    config = scheduled_worker_from_settings(settings)
    prepared = Object(configuration=config,
        bindings=[Object(media_key='Same', folder='Same', library='Movies'),
                  Object(media_key='TV/Same', folder='Same', library='TV')],
        plan=Object(moves=[Object(media_key='Same', library='Movies', source_stage='Waiting', destination_stage='Holding'),
                          Object(media_key='TV/Same', library='TV', source_stage='Waiting', destination_stage='Keep')]))
    return settings, config, prepared


def catalogs():
    return {'radarr': [{'id': 10, 'path': '/media/Movies/Same', 'monitored': True, 'secret': 'omit'}],
            'sonarr': [{'id': 20, 'path': '/media/TV/Same', 'monitored': False}]}


def resolver(settings, config, data, calls):
    def client(**kwargs):
        def fetch():
            calls.append(kwargs['service'])
            return deepcopy(data[kwargs['service']])
        return fetch
    with patch.object(module, 'ArrCatalogGET', client):
        return configured_arr_queue_resolver(settings=settings, config=config)


def test_routes_identical_names_by_service_preserves_monitoring_and_detaches():
    settings, config, prepared = inputs()
    data, calls = catalogs(), []
    resolve = resolver(settings, config, data, calls)
    settings['RADARR_APP_HOLDING_PATH'] = '/changed'
    requests = resolve(prepared)
    assert requests == {'Same': {'service': 'radarr', 'title_id': 10, 'root': '/arr-view/Movies_hold', 'monitored': False},
        'TV/Same': {'service': 'sonarr', 'title_id': 20, 'root': '/arr-view/TV_keep', 'monitored': False}}
    assert calls == ['radarr', 'sonarr']
    assert 'secret' not in str(requests) and 'key' not in str(requests)
    with pytest.raises(ArrCatalogError, match='replayed'):
        resolve(prepared)


@pytest.mark.parametrize('change', ['missing', 'bool-id', 'duplicate-id', 'duplicate-folder', 'wrong-source', 'bad-monitoring'])
def test_bad_identity_or_source_refuses_entire_request_set(change):
    settings, config, prepared = inputs()
    data, calls = catalogs(), []
    if change == 'missing': data['sonarr'] = []
    elif change == 'bool-id': data['radarr'][0]['id'] = True
    elif change == 'duplicate-id': data['radarr'].append(dict(data['radarr'][0], path='/media/Movies/Other'))
    elif change == 'duplicate-folder': data['radarr'].append(dict(data['radarr'][0], id=11))
    elif change == 'wrong-source': data['radarr'][0]['path'] = '/other/Same'
    else: data['radarr'][0]['monitored'] = None
    with pytest.raises((ArrCatalogError, ValueError)):
        resolver(settings, config, data, calls)(prepared)


def test_holding_to_keep_enables_monitoring():
    settings, config, prepared = inputs()
    data = catalogs()
    prepared.plan.moves[0].source_stage = 'Holding'
    prepared.plan.moves[0].destination_stage = 'Keep'
    data['radarr'][0]['path'] = '/arr-view/Movies_hold/Same'
    data['radarr'][0]['monitored'] = False
    assert resolver(settings, config, data, [])(prepared)['Same']['monitored'] is True


def test_partial_configuration_fails_before_transport_or_collection():
    settings, config, _ = inputs()
    settings['RADARR_API_KEY'] = ''
    with patch.object(module, 'ArrCatalogGET') as client:
        with pytest.raises(ValueError, match='Both Arr'):
            configured_arr_queue_resolver(settings=settings, config=config)
        client.assert_not_called()


@pytest.mark.parametrize('url', ['http://user:password@host', 'file:///tmp/catalog', 'http://host?key=secret',
    'http://host/#fragment', 'http://host:bad', 'http://host\n'])
def test_invalid_transport_configuration_never_opens_network(url):
    with pytest.raises(ValueError):
        ArrCatalogGET(service='radarr', base_url=url, token='synthetic')


def test_transport_failure_is_redacted_and_never_retried():
    from urllib.error import URLError
    client = ArrCatalogGET(service='radarr', base_url='http://fixture-radarr', token='private-key')
    with patch.object(client._opener, 'open', side_effect=URLError('private-key private-host')) as opened:
        with pytest.raises(ArrCatalogError) as error:
            client()
        assert 'private-key' not in str(error.value) and 'private-host' not in str(error.value)
        with pytest.raises(ArrCatalogError, match='no retry'):
            client()
        assert opened.call_count == 1
        request = opened.call_args.args[0]
        assert request.get_method() == 'GET'
        assert request.full_url == 'http://fixture-radarr/api/v3/movie'


def test_multiple_planned_movies_share_one_bounded_catalog_read():
    settings, config, prepared = inputs()
    data, calls = catalogs(), []
    data['radarr'].append({'id': 11, 'path': '/media/Movies/Other', 'monitored': True})
    prepared.bindings.append(Object(media_key='Other', folder='Other', library='Movies'))
    prepared.plan.moves.append(Object(media_key='Other', library='Movies', source_stage='Waiting', destination_stage='Holding'))
    assert len(resolver(settings, config, data, calls)(prepared)) == 3
    assert calls == ['radarr', 'sonarr']


def test_http_error_response_is_closed_without_garbage_collection():
    from io import BytesIO
    from urllib.error import HTTPError
    body = BytesIO(b'private response')
    error = HTTPError('http://fixture', 401, 'private message', {}, body)
    client = ArrCatalogGET(service='radarr', base_url='http://fixture', token='private-key')
    with patch.object(client._opener, 'open', side_effect=error):
        with pytest.raises(ArrCatalogError):
            client()
    assert body.closed


def test_total_response_deadline_closes_body_and_does_not_retry():
    from io import BytesIO
    body = BytesIO(b'[]')
    body.status = 200
    client = ArrCatalogGET(service='radarr', base_url='http://fixture', token='private-key')
    with patch.object(client._opener, 'open', return_value=body) as opened:
        with patch.object(module, 'monotonic', side_effect=[0, 11]):
            with pytest.raises(ArrCatalogError):
                client()
        assert body.closed
        with pytest.raises(ArrCatalogError, match='no retry'):
            client()
        assert opened.call_count == 1


def test_remote_trailing_slashes_accept_matching_and_unrelated_catalog_entries():
    settings, config, prepared = inputs()
    data, calls = catalogs(), []
    for records in data.values():
        records[0]['path'] += '/'
        records.append({'id': 99, 'path': '/other/Unrelated/', 'monitored': False})
    before = deepcopy(data)
    requests = resolver(settings, config, data, calls)(prepared)
    assert requests['Same']['title_id'] == 10
    assert requests['TV/Same']['title_id'] == 20
    assert data == before


@pytest.mark.parametrize('path', ['/media/Movies/Same//', '/media//Movies/Same/',
    '/media/Movies/../Same/', '/media/./Movies/Same/', '/', '//', 'relative/', None])
def test_remote_path_normalization_never_repairs_unsafe_paths(path):
    from app.arr_catalog import canonical_arr_record_path
    with pytest.raises(ValueError): canonical_arr_record_path(path)


def test_normalized_duplicate_title_folder_still_blocks():
    settings, config, prepared = inputs()
    data, calls = catalogs(), []
    data['radarr'].append({'id': 11, 'path': '/another/Same/', 'monitored': False})
    with pytest.raises(ArrCatalogError, match='Ambiguous'):
        resolver(settings, config, data, calls)(prepared)
