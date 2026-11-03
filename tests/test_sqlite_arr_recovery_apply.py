"""Explicit recovery against real bound live state and a GET-only HTTP fixture."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import sys
import threading

import pytest

from app import sqlite_live_binding as live, sqlite_release_profile as build
from app.sqlite_live_policy import DISABLED
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_arr_recovery_review import review, reconcile
from scripts.sqlite_preview_release_fixture import prepare_case

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Bound Linux live recovery')


@pytest.fixture
def bound(monkeypatch):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.command, self.path))
            if self.server.hook:
                self.server.hook()
            raw = json.dumps(self.server.records).encode()
            self.send_response(200); self.end_headers(); self.wfile.write(raw)
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.hook = None
    server.records = [dict(id=7, path='/remote/keep/Show', monitored=True)]
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    case, source, control, saved, values = prepare_case()
    values.update(DRY_RUN='false', MAX_ACTIONS_PER_RUN='2',
        SONARR_URL='http://127.0.0.1:' + str(server.server_port),
        SONARR_API_KEY='synthetic-private-token', **{key:'false' for key in DISABLED})
    monkeypatch.setattr(build, 'PROFILE', live.PROFILE)
    monkeypatch.setattr(build, 'SOURCE_REVISION', 'b' * 40)
    destination = Path(values['SONARR_KEEP_PATH']) / 'Show'; destination.mkdir()
    (destination / 'episode.mkv').write_bytes(b'disposable-episode')
    live.create_live_binding(settings=values)
    store = GuardedSQLiteStateStore(control / 'state.db')
    state, revision = store.load_with_revision()
    request = dict(service='sonarr', title_id=7, root='/remote/keep', monitored=True)
    state['keep_seen']['TV/Show'] = '2026-01-01T00:00:00'
    state['arr_sync_pending']['TV/Show'] = dict(stage='keep', **request)
    state['arr_sync_pending']['Unrelated'] = dict(stage='holding', service='radarr',
        title_id=8, root='/remote/holding', monitored=False)
    state[INTENTS_KEY] = dict(id='selected-operation', kind='arr_sync', phase='intent_recorded',
        details=dict(media_key='TV/Show', title_folder='Show', stage='keep', **request))
    state['unknown_recovery_extension'] = {'retain': [1, 'private']}
    store.save_if_revision(state, revision)
    claims = control / '.sqlite_scheduled_slots'; claims.mkdir()
    (claims / ('a' * 64 + '.json')).write_bytes(b'{"phase":"slot_claimed"}')
    try:
        yield dict(values=values, store=store, source=source, control=control,
            saved=saved, destination=destination, server=server, calls=calls)
    finally:
        server.shutdown(); server.server_close(); thread.join(); case.doCleanups()


def fingerprint(case):
    return review(settings=case['values'])['review_fingerprint']


def test_actual_live_recovery_clears_only_selected_queue_and_intent(bound):
    before, revision = bound['store'].load_with_revision()
    retained = {p: p.read_bytes() for p in (bound['source'], bound['saved'],
        bound['destination'] / 'episode.mkv',
        * (bound['control'] / '.sqlite_scheduled_slots').iterdir())}
    digest = fingerprint(bound); bound['calls'].clear()
    report = reconcile(settings=bound['values'], expected_fingerprint=digest)
    expected = deepcopy(before)
    expected.pop(INTENTS_KEY); expected['arr_sync_pending'].pop('TV/Show')
    assert bound['store'].load_with_revision() == (expected, revision + 1)
    assert report['status'] == 'arr_intent_reconciled'
    assert bound['calls'] == [('GET', '/api/v3/series')] * 2
    assert all(p.read_bytes() == raw for p, raw in retained.items())
    assert live.validate_live_binding(settings=bound['values'], for_execution=True)
    with pytest.raises(RuntimeError):
        reconcile(settings=bound['values'], expected_fingerprint=digest)
    assert len(bound['calls']) == 2  # No replay even when the exact command repeats.


@pytest.mark.parametrize('change', ['fingerprint', 'remote', 'source_lock', 'control_lock',
    'destination', 'database', 'state', 'settings', 'profile'])
def test_refusal_never_clears_intent(bound, monkeypatch, change):
    from contextlib import ExitStack
    from app.sqlite_lock import _exclusive_lock
    before = bound['store'].load_with_revision()
    digest = fingerprint(bound); bound['calls'].clear()
    with ExitStack() as stack:
        if change == 'fingerprint': digest = '0' * 64
        elif change == 'remote': bound['server'].records[0]['monitored'] = False
        elif change == 'source_lock':
            stack.enter_context(_exclusive_lock(bound['source'].with_name(
                bound['source'].name + '.migration.lock'), 'fixture'))
        elif change == 'control_lock':
            stack.enter_context(_exclusive_lock(bound['control'] / '.sqlite_runner.lock', 'fixture'))
        elif change == 'destination':
            bound['server'].hook = lambda: (bound['destination'] / 'new.mkv').touch()
        elif change == 'database':
            def replace():
                bound['server'].hook = None
                db = bound['control'] / 'state.db'
                raw = db.read_bytes(); db.rename(bound['control'] / 'retained.db'); db.write_bytes(raw)
            bound['server'].hook = replace
        elif change == 'state':
            def mutate():
                bound['server'].hook = None
                state, revision = bound['store'].load_with_revision()
                state['unknown_recovery_extension']['changed'] = True
                bound['store'].save_if_revision(state, revision)
            bound['server'].hook = mutate
        elif change == 'settings': bound['saved'].write_text('{"ENABLE_TV":"false"}')
        elif change == 'profile': monkeypatch.setattr(build, 'PROFILE', 'scheduled-preview-v1')
        with pytest.raises((RuntimeError, ValueError)):
            reconcile(settings=bound['values'], expected_fingerprint=digest)
    state, revision = bound['store'].load_with_revision()
    assert state[INTENTS_KEY] == before[0][INTENTS_KEY]
    assert state['arr_sync_pending'] == before[0]['arr_sync_pending']
    assert revision == before[1] + (change == 'state')
    if change not in ('remote', 'destination', 'database', 'state'):
        assert bound['calls'] == []


@pytest.mark.parametrize('boundary', ['before_commit', 'after_commit'])
def test_actual_sigkill_has_atomic_clearance_and_never_replays(bound, boundary):
    before, revision = bound['store'].load_with_revision()
    digest = fingerprint(bound)
    pid = os.fork()
    if pid == 0:
        try:
            original = GuardedSQLiteStateStore.save_if_revision
            def kill_at_commit(self, state, expected_revision):
                if boundary == 'before_commit': os.kill(os.getpid(), signal.SIGKILL)
                original(self, state, expected_revision)
                os.kill(os.getpid(), signal.SIGKILL)
            GuardedSQLiteStateStore.save_if_revision = kill_at_commit
            reconcile(settings=bound['values'], expected_fingerprint=digest)
        finally: os._exit(99)
    _, status = os.waitpid(pid, 0)
    assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    state, current = bound['store'].load_with_revision()
    if boundary == 'before_commit':
        assert (state, current) == (before, revision)
    else:
        expected = deepcopy(before); expected.pop(INTENTS_KEY)
        expected['arr_sync_pending'].pop('TV/Show')
        assert (state, current) == (expected, revision + 1)
        with pytest.raises(RuntimeError):
            reconcile(settings=bound['values'], expected_fingerprint=digest)
    assert live.validate_live_binding(settings=bound['values'])


@pytest.mark.parametrize('failure', ['concurrent_commit', 'lost_commit_ack'])
def test_checkpoint_failure_is_not_retried_or_misreported(bound, monkeypatch, failure):
    before, revision = bound['store'].load_with_revision()
    digest = fingerprint(bound)
    original = GuardedSQLiteStateStore.save_if_revision
    saves = []
    def fail(self, state, expected_revision):
        saves.append(1)
        if failure == 'concurrent_commit':
            concurrent = deepcopy(before)
            concurrent['unknown_recovery_extension']['concurrent'] = True
            original(self, concurrent, expected_revision)
            return original(self, state, expected_revision)  # Must lose the CAS.
        original(self, state, expected_revision)
        raise OSError('synthetic-private-write-ack-lost')
    monkeypatch.setattr(GuardedSQLiteStateStore, 'save_if_revision', fail)
    with pytest.raises((RuntimeError, OSError)):
        reconcile(settings=bound['values'], expected_fingerprint=digest)
    assert len(saves) == 1
    state, current = bound['store'].load_with_revision()
    assert current == revision + 1
    if failure == 'concurrent_commit':
        assert state[INTENTS_KEY] == before[INTENTS_KEY]
        assert state['unknown_recovery_extension']['concurrent'] is True
    else:
        assert INTENTS_KEY not in state and 'TV/Show' not in state['arr_sync_pending']
        with pytest.raises(RuntimeError):
            reconcile(settings=bound['values'], expected_fingerprint=digest)
    assert len(saves) == 1
