from copy import deepcopy
from io import BytesIO
from unittest.mock import Mock, patch
from urllib.error import HTTPError
import pytest

from app.arr_import_transport import ArrImportHTTP, ArrImportError


def client():
    return ArrImportHTTP(service='sonarr', base_url='http://private-server.invalid', token='private-token')


def payload():
    return dict(title='Show', titleSlug='show', tvdbId=100, qualityProfileId=2,
        path='/media/TV/Show', rootFolderPath='/media/TV', monitored=False, tags=[], year=2020,
        addOptions={'monitor':'none','searchForMissingEpisodes':False,'searchForCutoffUnmetEpisodes':False},
        seriesType='standard', seasonFolder=True, seasons=[{'seasonNumber':1,'monitored':False}],
        monitorNewItems='none')


@pytest.mark.parametrize('change', ['monitored', 'search', 'future_seasons', 'season', 'extra', 'outside_root'])
def test_unsafe_create_payload_refused_before_transport(change):
    transport, body = client(), payload()
    if change == 'monitored': body['monitored'] = True
    elif change == 'search': body['addOptions']['searchForMissingEpisodes'] = True
    elif change == 'future_seasons': body['monitorNewItems'] = 'all'
    elif change == 'season': body['seasons'][0]['monitored'] = True
    elif change == 'extra': body['moveFiles'] = True
    else: body['path'] = '/other/Show'
    with patch.object(transport._opener, 'open') as opened:
        with pytest.raises(ArrImportError): transport.create(body)
        opened.assert_not_called()


@pytest.mark.parametrize('raw', [b'{"version":"4.0","version":"4.1"}', b'{"value":NaN}', b'private-token-error', b'null'])
def test_bad_json_is_redacted_and_body_closed(raw):
    transport = client(); response = BytesIO(raw); response.status = 200
    with patch.object(transport._opener,'open',return_value=response):
        with pytest.raises(ArrImportError) as caught: transport.get('system/status')
    assert response.closed and 'private-token' not in str(caught.value)


def test_http_failure_body_closed_and_no_automatic_create_retry():
    transport = client(); response = BytesIO(b'private-token')
    error = HTTPError('http://private-server.invalid', 503, 'private-token', {}, response)
    with patch.object(transport._opener,'open',side_effect=error) as opened:
        with pytest.raises(ArrImportError): transport.create(payload())
        with pytest.raises(ArrImportError, match='already_used'): transport.create(payload())
        assert opened.call_count == 1
    assert response.closed and 'private-token' not in repr(transport)


@pytest.mark.parametrize('route', ['command', '../system/status', 'series/1?deleteFiles=true', 'movie', 'series/0'])
def test_arbitrary_routes_cannot_be_requested(route):
    transport = client()
    with patch.object(transport._opener,'open') as opened:
        with pytest.raises(ArrImportError): transport.get(route)
        opened.assert_not_called()
