from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError
import pytest

from app import sqlite_arr_title_transport as module
from app.sqlite_arr_title_transport import ArrTitleUpdate, ArrTitleTransportError

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
