from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS
from app.sqlite_operation_coordinator import INTENTS_KEY
from scripts.sqlite_arr_recovery_review import review


@pytest.fixture
def case(tmp_path):
    roots = {}
    settings = dict(ENABLE_MOVIES='false', ENABLE_TV='true',
        SQLITE_DAILY_RUN_TIME='02:00', SQLITE_DAILY_RUN_TIMEZONE='America/Los_Angeles',
        SQLITE_STATE_FILE=str(tmp_path / 'state.db'), SONARR_API_KEY='private-test-token',
        SONARR_URL='http://127.0.0.1:1')
    for stage in ('transient', 'holding', 'keep', 'removal'):
        roots[stage] = tmp_path / stage
        roots[stage].mkdir()
        settings['SONARR_' + stage.upper() + '_PATH'] = str(roots[stage])
    (roots['keep'] / 'Show').mkdir()
    state = {section: {} for section in SECTIONS}
    state['keep_seen']['TV/Show'] = '2026-01-01T00:00:00'
    request = dict(service='sonarr', title_id=7, root='/remote/keep', monitored=True)
    state['arr_sync_pending']['TV/Show'] = dict(stage='keep', **request)
    state[INTENTS_KEY] = dict(id='operation', kind='arr_sync', phase='intent_recorded',
        details=dict(media_key='TV/Show', title_folder='Show', stage='keep', **request))
    state['private_extension'] = {'preserve': 'unknown'}
    write_offline_snapshot(state, settings['SQLITE_STATE_FILE'])
    return settings, roots


def test_real_http_reads_twice_and_changes_no_database_bytes(case):
    settings, roots = case
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.path, self.headers.get('X-Api-Key')))
            raw = json.dumps([dict(id=7, path='/remote/keep/Show/', monitored=True)]).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(raw)
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    settings['SONARR_URL'] = 'http://127.0.0.1:' + str(server.server_port)
    from pathlib import Path
    database = Path(settings['SQLITE_STATE_FILE'])
    before = database.read_bytes()
    try:
        result = review(settings=settings)
    finally:
        server.shutdown(); thread.join(); server.server_close()
    assert result['status'] == 'arr_recovery_review_matches'
    assert result['clearance_authorized'] is False
    assert result['remote_readbacks'] == 2
    assert calls == [('/api/v3/series', 'private-test-token')] * 2
    assert database.read_bytes() == before
    assert 'private' not in json.dumps(result)


@pytest.mark.parametrize('failure', ['wrong_path', 'wrong_monitoring', 'duplicate',
    'changed_second_read', 'replace_title', 'second_stage', 'state_change'])
def test_review_refuses_mismatch_or_concurrent_change(case, monkeypatch, failure):
    settings, roots = case
    calls = []
    record = dict(id=7, path='/remote/keep/Show', monitored=True)
    def factory(**kwargs):
        def fetch():
            calls.append(1)
            result = deepcopy(record)
            if failure == 'wrong_path': result['path'] = '/remote/keep/Different'
            if failure == 'wrong_monitoring': result['monitored'] = False
            if failure == 'changed_second_read' and len(calls) == 2:
                result['monitored'] = False
            if failure == 'replace_title' and len(calls) == 1:
                (roots['keep'] / 'Show').rename(roots['keep'] / 'Old')
                (roots['keep'] / 'Show').mkdir()
            if failure == 'second_stage': (roots['holding'] / 'Show').mkdir(exist_ok=True)
            if failure == 'state_change' and len(calls) == 1:
                from app.sqlite_audit_session import RevisionedAuditSession
                from app.state_store import GuardedSQLiteStateStore
                session = RevisionedAuditSession(GuardedSQLiteStateStore(settings['SQLITE_STATE_FILE']))
                session.state['private_extension']['new'] = True
                session.checkpoint()
            return [result, result] if failure == 'duplicate' else [result]
        return fetch
    monkeypatch.setattr('scripts.sqlite_arr_recovery_review.ArrCatalogGET', factory)
    with pytest.raises(RuntimeError): review(settings=settings)
    from app.state_store import GuardedSQLiteStateStore
    state, revision = GuardedSQLiteStateStore(settings['SQLITE_STATE_FILE']).load_with_revision()
    assert state[INTENTS_KEY]['id'] == 'operation'
    assert 'TV/Show' in state['arr_sync_pending']
    assert revision == (1 if failure == 'state_change' else 0)
