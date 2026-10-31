from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from copy import deepcopy
import pytest
from app.sqlite_jellyfin_refresh import refresh_after_completed_live_run


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            self.server.calls.append((self.path, self.headers.get('Authorization'), self.headers.get('X-Emby-Token')))
            self.send_response(self.server.code)
            if self.server.code == 302:
                self.send_header('Location', '/unexpected')
            self.end_headers()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.calls = []; server.code = 204
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    yield server
    server.shutdown(); server.server_close(); thread.join()


def inputs(server):
    return ({'JELLYFIN_HOST_URL': f'http://127.0.0.1:{server.server_port}',
        'JELLYFIN_API_TOKEN': 'synthetic-token', 'JELLYFIN_REFRESH_AFTER_AUDIT': 'true', 'DRY_RUN': 'false'},
        {'status': 'disposable_scheduled_routed_slot_complete', 'completed': [{'media_key':'Movie'}]})


def test_completed_batch_requests_once_without_mutating_result(server):
    settings, result = inputs(server); before = deepcopy(result)
    assert refresh_after_completed_live_run(settings=settings, result=result)['status'] == 'requested'
    assert server.calls == [('/Library/Refresh', 'MediaBrowser Token="synthetic-token"', 'synthetic-token')]
    assert result == before


@pytest.mark.parametrize('change', ['disabled','preview','empty','uncertain'])
def test_no_request_for_disabled_preview_empty_or_uncertain_batch(server, change):
    settings, result = inputs(server)
    if change == 'disabled': settings['JELLYFIN_REFRESH_AFTER_AUDIT'] = 'false'
    if change == 'preview': settings['DRY_RUN'] = 'true'
    if change == 'empty': result['completed'] = []
    if change == 'uncertain': result['status'] = 'stopped'
    assert refresh_after_completed_live_run(settings=settings,result=result)['status'] == 'not_requested'
    assert server.calls == []


@pytest.mark.parametrize('code', [302,401,500])
def test_failed_or_redirected_request_never_retries_or_changes_completed_moves(server, code, capsys):
    settings, result = inputs(server); before = deepcopy(result); server.code = code
    outcome = refresh_after_completed_live_run(settings=settings,result=result)
    assert outcome == {'status':'failed_or_uncertain','scan_completion_verified':False}
    assert len(server.calls) == 1 and result == before
    assert 'synthetic-token' not in capsys.readouterr().out


def test_exhausted_deadline_never_sends_request(server):
    settings, result = inputs(server)
    assert refresh_after_completed_live_run(settings=settings,result=result,maximum_seconds=0)['status'] == 'failed_or_uncertain'
    assert server.calls == []
