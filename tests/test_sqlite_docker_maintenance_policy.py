"""Offline rule tests only; never contact a Docker endpoint."""
import json
import pytest
from app.sqlite_docker_maintenance_policy import authorize_maintenance_request as authorize


def request(method='GET', uri='/info', **extra):
    return {'RequestMethod': method, 'RequestURI': uri, 'RequestHeader': {}, **extra}


@pytest.mark.parametrize('method,uri', [('GET','/_ping'), ('HEAD','/_ping'), ('GET','/info'),
    ('GET','/version'), ('GET','/containers/json'), ('GET','/containers/json?all=1')])
def test_only_explicit_observations_allow(method, uri):
    assert authorize(request(method, uri))['Allow'] is True


@pytest.mark.parametrize('method,uri', [('POST','/containers/create'),
    ('POST','/containers/writer/start'), ('POST','/containers/writer/restart'),
    ('POST','/containers/writer/unpause'), ('POST','/containers/writer/update'),
    ('POST','/containers/writer/exec'), ('POST','/exec/abc/start'),
    ('PUT','/containers/writer/archive'), ('DELETE','/containers/writer'),
    ('POST','/build'), ('POST','/grpc'), ('GET','/grpc'),
    ('GET','/containers/writer/attach/ws'), ('GET','/events'),
    ('GET','/containers/writer/logs'), ('GET','/v1.54/info'),
    ('GET','//info'), ('GET','http://daemon/info'), ('GET','/x/../info'),
    ('GET','/%69nfo'), ('GET','/info#fragment'), ('GET','/info?all=1'),
    ('GET','/containers/json?all=1&all=0'), ('GET','/containers/json?all=true'),
    ('GET','/info\n'), ('GET','/unknown')])
def test_mutations_streams_unknown_versions_and_ambiguous_paths_deny(method, uri):
    assert authorize(request(method, uri))['Allow'] is False


@pytest.mark.parametrize('headers', [{'Upgrade':['websocket']}, {'Connection':['upgrade']},
    {'Content-Length':['0']}, {'Transfer-Encoding':['chunked']}, {'Content-Type':['application/json']},
    {'X-HTTP-Method-Override':['POST']}, {'bad header':['value']}, {'Host':'not-a-list'}])
def test_upgrade_framing_and_malformed_metadata_deny(headers):
    assert authorize(request(RequestHeader=headers))['Allow'] is False


@pytest.mark.parametrize('value', [None, [], {}, {'RequestMethod':'GET'},
    {'RequestMethod':'GET','RequestURI':'/info'}, request(RequestBody='c2VjcmV0')])
def test_missing_unknown_or_body_bearing_request_denies(value):
    assert authorize(value)['Allow'] is False


def test_user_identity_or_headers_never_override_denial_or_leak():
    result = authorize(request('POST', '/containers/secret/start', User='root',
        RequestHeader={'Authorization':['Bearer secret'], 'X-Maintenance-Owner':['secret']}))
    assert result == {'Allow':False,'Msg':'Maintenance request denied','Err':''}
    assert 'secret' not in json.dumps(result)


def test_conflicting_header_shapes_and_empty_delimiters_deny():
    assert authorize(request(RequestHeaders={}))['Allow'] is False
    assert authorize(request(uri='/info#'))['Allow'] is False
    assert authorize(request(uri='/info?'))['Allow'] is False
