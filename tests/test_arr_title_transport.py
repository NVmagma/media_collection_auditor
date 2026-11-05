from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError
import pytest

from app import arr_title_transport as module
from app.arr_title_transport import ArrTitleUpdate, ArrTitleTransportError

DETAILS = dict(service='radarr', title_id=42, root='/arr/keep', monitored=False)


def client():
    return ArrTitleUpdate(service='radarr', base_url='http://private-host',
        token='private-token', source_path='/arr/holding/Title', title_folder='Title')


@pytest.mark.parametrize('body', [b'{"id":42,"id":43}', b'{"id":NaN}', b'[]', b'not json'])
def test_invalid_json_closes_response_and_consumes_attempt(body):
    transport = client(); response = BytesIO(body); response.status = 200
    with patch.object(transport._opener, 'open', return_value=response) as opened:
        with pytest.raises(ArrTitleTransportError): transport(DETAILS)
        assert response.closed
        with pytest.raises(ArrTitleTransportError, match='no retry'): transport(DETAILS)
        assert opened.call_count == 1


def test_http_error_body_is_closed_and_secrets_are_redacted():
    transport = client(); response = BytesIO(b'private-token')
    error = HTTPError('http://private-host', 401, 'private-token', {}, response)
    with patch.object(transport._opener, 'open', side_effect=error) as opened:
        with pytest.raises(ArrTitleTransportError) as caught: transport(DETAILS)
        assert response.closed
        assert 'private-token' not in str(caught.value) and 'private-host' not in str(caught.value)
        with pytest.raises(ArrTitleTransportError): transport(DETAILS)
        assert opened.call_count == 1
    assert 'private-token' not in repr(transport)


def test_one_deadline_spans_all_four_requests():
    transport = client(); deadlines = []
    def request(method, url, deadline, body=None):
        deadlines.append(deadline)
        return {'id': 42, 'path': '/arr/holding/Title' if len(deadlines) == 1 else '/arr/keep/Title',
                'monitored': False}
    with patch.object(transport, '_request', side_effect=request):
        assert transport(DETAILS) is True
    assert len(deadlines) == 4 and len(set(deadlines)) == 1


def test_total_read_deadline_closes_body_and_never_puts():
    transport = client(); response = BytesIO(b'{}'); response.status = 200
    with patch.object(transport._opener, 'open', return_value=response) as opened:
        with patch.object(module, 'monotonic', side_effect=[0, 1, 11]):
            with pytest.raises(ArrTitleTransportError): transport(DETAILS)
        assert response.closed and opened.call_count == 1
        assert opened.call_args.args[0].get_method() == 'GET'


def test_body_limit_closes_body_before_put():
    transport = client(); response = BytesIO(b' ' * (8 * 1024 * 1024 + 1)); response.status = 200
    with patch.object(transport._opener, 'open', return_value=response) as opened:
        with pytest.raises(ArrTitleTransportError): transport(DETAILS)
        assert response.closed and opened.call_count == 1


def test_service_mismatch_cannot_send():
    transport = client()
    with patch.object(transport._opener, 'open') as opened:
        with pytest.raises(ArrTitleTransportError): transport(dict(DETAILS, service='sonarr'))
        opened.assert_not_called()


def test_outer_run_deadline_prevents_new_http_without_reset():
    transport = ArrTitleUpdate(service='radarr', base_url='http://private-host',
        token='private-token', source_path='/arr/holding/Title', title_folder='Title', deadline_tick=0)
    with patch.object(transport._opener, 'open') as opened:
        with pytest.raises(ArrTitleTransportError): transport(DETAILS)
        opened.assert_not_called()


def test_remote_source_and_readback_trailing_slashes_are_equivalent():
    transport = client()
    methods = []
    def request(method, url, deadline, body=None):
        methods.append(method)
        if method == 'PUT':
            import json
            assert json.loads(body)['path'] == '/arr/keep/Title'
        return {'id': 42, 'path': ('/arr/holding/Title/' if len(methods) == 1 else '/arr/keep/Title/'),
                'monitored': False}
    with patch.object(transport, '_request', side_effect=request):
        assert transport(DETAILS) is True
    assert methods == ['GET', 'PUT', 'GET', 'GET']


@pytest.mark.parametrize('path', ['/arr/holding/Title//', '/arr//holding/Title/', '/arr/holding/../Title/'])
def test_unsafe_remote_source_path_never_puts(path):
    transport = client()
    with patch.object(transport, '_request', return_value={'id':42,'path':path,'monitored':False}) as request:
        with pytest.raises(ArrTitleTransportError): transport(DETAILS)
        assert request.call_count == 1


@pytest.mark.parametrize('acknowledgment', [200,202])
def test_sonarr_acknowledgment_always_requires_two_independent_readbacks(acknowledgment):
    transport = ArrTitleUpdate(service='sonarr',base_url='http://fixture.invalid',
        token='synthetic-token',source_path='/arr/holding/Title',title_folder='Title')
    old = {'id':42,'path':'/arr/holding/Title','monitored':False,'seasons':[{'seasonNumber':1,'monitored':False}]}
    new = {**old,'path':'/arr/keep/Title','monitored':True}
    responses=[]
    for status,row in [(200,old),(acknowledgment,new),(200,new),(200,new)]:
        response = BytesIO(__import__('json').dumps(row).encode()); response.status = status
        responses.append(response)
    with patch.object(transport._opener,'open',side_effect=responses) as opened:
        assert transport(dict(DETAILS,service='sonarr',monitored=True)) is True
    assert [call.args[0].get_method() for call in opened.call_args_list] == ['GET','PUT','GET','GET']
    assert all(response.closed for response in responses)


def test_sonarr_202_with_mismatched_readback_stays_uncertain():
    import json
    transport = ArrTitleUpdate(service='sonarr',base_url='http://fixture.invalid',
        token='synthetic-token',source_path='/arr/holding/Title',title_folder='Title')
    old = {'id':42,'path':'/arr/holding/Title','monitored':False}
    new = {**old,'path':'/arr/keep/Title','monitored':True}
    responses=[]
    for status,row in [(200,old),(202,new),(200,old)]:
        response = BytesIO(json.dumps(row).encode()); response.status = status; responses.append(response)
    with patch.object(transport._opener,'open',side_effect=responses) as opened:
        with pytest.raises(ArrTitleTransportError): transport(dict(DETAILS,service='sonarr',monitored=True))
        with pytest.raises(ArrTitleTransportError): transport(dict(DETAILS,service='sonarr',monitored=True))
        assert opened.call_count == 3
