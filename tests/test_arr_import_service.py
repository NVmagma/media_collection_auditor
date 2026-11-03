"""Real loopback Arr registration with bound live SQLite and disposable media."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import sys
import threading
from urllib.parse import urlsplit

import pytest

from app import arr_import_service as imports, sqlite_live_binding as live, sqlite_release_profile as build
from app.arr_import_transport import ArrImportError
from app.sqlite_live_policy import DISABLED
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_preview_release_fixture import prepare_case

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux bound live state')


@pytest.fixture(params=['Movies', 'TV'])
def bound(monkeypatch, request):
    library, stage, remote_alias = (request.param if isinstance(request.param, tuple)
        else (request.param, 'Waiting', None))
    case, source, control, saved, values = prepare_case()
    resource = 'movie' if library == 'Movies' else 'series'
    provider = 'tmdbId' if library == 'Movies' else 'tvdbId'
    prefix = 'RADARR' if library == 'Movies' else 'SONARR'
    field = 'TRANSIENT' if stage == 'Waiting' else stage.upper()
    root = values[prefix + '_' + field + '_PATH']
    directory = Path(root) / 'Import existing'; directory.mkdir()
    media = directory/'episode.mkv'; media.write_bytes(b'disposable existing content')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def respond(self, value, status=200):
            raw = json.dumps(value).encode()
            self.send_response(status); self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            self.server.calls.append(('GET', self.path))
            path = urlsplit(self.path).path.rsplit('/', 1)[-1]
            if path == 'status': return self.respond({'version': self.server.version})
            if path == 'qualityprofile': return self.respond([self.server.profile])
            if path == 'rootfolder': return self.respond([{'id': 1, 'path': self.server.root, 'accessible': True}])
            if path == 'lookup': return self.respond([self.server.metadata])
            if path == resource: return self.respond(self.server.records)
            if path == '77' and self.server.records:
                row = deepcopy(self.server.records[0])
                if self.server.mode == 'wrong_readback': row['monitored'] = True
                return self.respond(row)
            self.send_response(404); self.end_headers()
        def do_POST(self):
            self.server.calls.append(('POST', self.path))
            assert self.path == '/api/v3/' + resource
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.server.payloads.append(body)
            self.server.records.append(dict(body, id=77))
            if self.server.mode == 'path_race':
                self.server.records.append(dict(body, id=88, **{provider:999}))
            if self.server.mode == 'lost_ack':
                self.connection.shutdown(socket.SHUT_RDWR); self.connection.close(); return
            return self.respond(self.server.records[0], self.server.create_status)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.version = '6.4.4.10685' if library == 'Movies' else '4.0.20.3014'
    server.records, server.calls, server.payloads = [], [], []
    server.profile = {'id': 2, 'name': 'Existing HD', 'cutoff': 1}
    server.mode = 'normal'
    server.create_status = 201
    server.root = remote_alias or root
    server.metadata = {'title': 'Import Existing', 'titleSlug': 'import-existing',
        'year': 2020, provider: 100, 'seasons': [{'seasonNumber': 1, 'monitored': True}],
        'apiKey': 'synthetic-private-lookup-field', 'addOptions': {'searchForMovie': True}, 'monitored': True}
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    values.update(DRY_RUN='false', MAX_ACTIONS_PER_RUN='2', **{key:'false' for key in DISABLED})
    values[prefix + '_URL'] = 'http://127.0.0.1:' + str(server.server_port)
    values[prefix + '_API_KEY'] = 'synthetic-private-token'
    if remote_alias: values[prefix + '_APP_' + stage.upper() + '_PATH'] = remote_alias
    monkeypatch.setattr(build, 'PROFILE', live.PROFILE)
    monkeypatch.setattr(build, 'SOURCE_REVISION', 'b' * 40)
    live.create_live_binding(settings=values)
    claims = control/'.sqlite_scheduled_slots'; claims.mkdir()
    claim = claims/('a'*64 + '.json'); claim.write_bytes(b'{"phase":"slot_claimed"}')
    selection = {'library': library, 'folder': directory.name, 'provider_id': 100, 'quality_profile_id': 2}
    store = GuardedSQLiteStateStore(control/'state.db')
    state, revision = store.load_with_revision()
    state['import_test_extension'] = {'retained': ['synthetic-private-state', 1]}
    store.save_if_revision(state, revision)
    try: yield dict(values=values, selection=selection, store=store, server=server,
        source=source, saved=saved, media=media, directory=directory, claim=claim, control=control,
        stage=stage, remote_root=server.root)
    finally:
        server.shutdown(); server.server_close(); thread.join(); case.doCleanups()


def review(case): return imports.review(selection=case['selection'], settings=case['values'])


def apply(case, report):
    return imports.apply(selection=case['selection'], settings=case['values'],
        expected_fingerprint=report['review_fingerprint'])


@pytest.mark.parametrize('create_status', [200, 201])
def test_existing_media_import_is_unmonitored_no_search_and_preserves_tracking(bound, create_status):
    bound['server'].create_status = create_status
    before = bound['store'].load_with_revision()
    originals = {p: p.read_bytes() for p in (bound['source'], bound['saved'], bound['media'], bound['claim'])}
    report = review(bound)
    assert bound['store'].load_with_revision() == before
    assert not bound['server'].payloads and 'synthetic-private' not in str(report)
    outcome = apply(bound, report)
    assert outcome['status'] == 'existing_media_import_verified'
    assert bound['store'].load_with_revision() == (before[0], before[1] + 2)
    assert len(bound['server'].payloads) == 1
    body = bound['server'].payloads[0]
    assert body['path'] == str(bound['directory']) and body['monitored'] is False
    assert body['qualityProfileId'] == 2 and body['addOptions']['monitor'] == 'none'
    assert 'apiKey' not in body and 'synthetic-private' not in json.dumps(body)
    if bound['selection']['library'] == 'TV':
        assert body['addOptions']['searchForMissingEpisodes'] is False
        assert body['addOptions']['searchForCutoffUnmetEpisodes'] is False
        assert body['monitorNewItems'] == 'none'
        assert all(s['monitored'] is False for s in body['seasons'])
    else: assert body['addOptions']['searchForMovie'] is False
    assert all(p.read_bytes() == data for p, data in originals.items())
    assert live.validate_live_binding(settings=bound['values'], for_execution=True)
    with pytest.raises(ArrImportError): apply(bound, report)
    assert len(bound['server'].payloads) == 1


@pytest.mark.parametrize('change', ['profile', 'media', 'folder', 'provider_duplicate', 'path_duplicate',
    'version', 'profile_choice', 'provider_choice', 'extra_flags', 'symlink', 'no_media', 'empty_media', 'duplicate_stage'])
def test_changed_review_never_creates_an_arr_record(bound, change):
    report = review(bound)
    if change == 'profile': bound['server'].profile['cutoff'] = 99
    elif change == 'media': bound['media'].write_bytes(b'changed')
    elif change == 'folder':
        bound['directory'].rename(bound['directory'].with_name('retained'))
        bound['directory'].mkdir(); (bound['directory']/'episode.mkv').write_bytes(b'new')
    elif change in ('provider_duplicate', 'path_duplicate'):
        provider = 'tmdbId' if bound['selection']['library'] == 'Movies' else 'tvdbId'
        bound['server'].records = [{'id': 55, provider: 100 if change == 'provider_duplicate' else 999,
            'path': '/other/Title' if change == 'provider_duplicate' else str(bound['directory'])}]
    elif change == 'version': bound['server'].version = '99.0.0'
    elif change == 'profile_choice': bound['selection']['quality_profile_id'] = 3
    elif change == 'provider_choice': bound['selection']['provider_id'] = 101
    elif change == 'extra_flags': bound['selection']['monitored'] = True
    elif change == 'symlink': (bound['directory']/'linked.mkv').symlink_to(bound['media'])
    elif change == 'no_media': bound['media'].unlink()
    elif change == 'empty_media': bound['media'].write_bytes(b'')
    elif change == 'duplicate_stage':
        prefix = 'RADARR' if bound['selection']['library'] == 'Movies' else 'SONARR'
        (Path(bound['values'][prefix + '_HOLDING_PATH'])/bound['directory'].name).mkdir()
    before = bound['store'].load_with_revision()
    with pytest.raises((RuntimeError, ValueError, OSError)): apply(bound, report)
    assert bound['store'].load_with_revision() == before
    assert not bound['server'].payloads


def test_options_and_lookup_project_only_public_choices(bound):
    result = imports.options(library=bound['selection']['library'], settings=bound['values'])
    assert result['quality_profiles'] == [{'id':2,'name':'Existing HD'}]
    assert 'Import existing' in result['folders']
    found = imports.lookup(library=bound['selection']['library'], term='Import', settings=bound['values'])
    assert found['matches'] == [{'provider_id':100,'title':'Import Existing','year':2020}]
    assert 'synthetic-private' not in str(result) + str(found)
    assert not bound['server'].payloads


@pytest.mark.parametrize('bound', [
    ('Movies', 'Holding', None), ('Movies', 'Keep', None), ('Movies', 'Removal', None),
    ('TV', 'Holding', None), ('TV', 'Keep', None), ('TV', 'Removal', None),
    ('TV', 'Holding', '/arr/TV_hold')], indirect=True)
def test_import_preserves_each_current_stage_and_app_path_alias(bound):
    before = bound['store'].load_with_revision()
    media_before = bound['media'].read_bytes()
    report = review(bound)
    assert report['stage'] == bound['stage']
    assert report['path'] == bound['remote_root'] + '/' + bound['directory'].name
    apply(bound, report)
    assert bound['media'].read_bytes() == media_before and bound['directory'].is_dir()
    assert bound['store'].load_with_revision() == (before[0], before[1] + 2)
    assert bound['server'].payloads[0]['path'] == report['path']


@pytest.mark.parametrize('profile', ['sealed', 'scheduled-preview-v1'])
def test_other_release_profiles_cannot_create_records(bound, monkeypatch, profile):
    report = review(bound); bound['server'].calls.clear()
    monkeypatch.setattr(build, 'PROFILE', profile)
    with pytest.raises(ArrImportError, match='live_import_unavailable'): apply(bound, report)
    assert not bound['server'].calls and not bound['server'].payloads


@pytest.mark.parametrize('mode', ['lost_ack', 'wrong_readback', 'path_race'])
def test_uncertain_import_retains_intent_and_explicit_get_only_recovery(bound, mode):
    before, revision = bound['store'].load_with_revision()
    report = review(bound); bound['server'].mode = mode
    with pytest.raises(ArrImportError): apply(bound, report)
    state, current = bound['store'].load_with_revision()
    assert state[INTENTS_KEY]['kind'] == 'arr_import' and current == revision + 1
    with pytest.raises(RuntimeError): live.validate_live_binding(settings=bound['values'], for_execution=True)
    with pytest.raises(RuntimeError): apply(bound, report)
    assert len(bound['server'].payloads) == 1
    bound['server'].mode = 'normal'
    if mode == 'path_race': bound['server'].records.pop()
    recovered = imports.recover(settings=bound['values'])
    assert recovered['status'] == 'import_outcome_matches'
    assert INTENTS_KEY in bound['store'].load_with_revision()[0]
    result = imports.recover(settings=bound['values'], expected_fingerprint=recovered['review_fingerprint'])
    assert result['arr_create_requests_sent'] == 0
    assert bound['store'].load_with_revision() == (before, revision + 2)
    assert len(bound['server'].payloads) == 1
    with pytest.raises(ArrImportError): imports.recover(settings=bound['values'])


@pytest.mark.parametrize('which', ['source', 'control'])
def test_worker_lock_prevents_import_before_http(bound, which):
    from app.sqlite_lock import _exclusive_lock, StateLockBusy
    report = review(bound); bound['server'].calls.clear()
    path = (bound['source'].with_name(bound['source'].name+'.migration.lock') if which == 'source'
        else bound['control']/'.sqlite_runner.lock')
    with _exclusive_lock(path, 'fixture'):
        with pytest.raises(StateLockBusy): apply(bound, report)
    assert bound['server'].calls == []


@pytest.mark.parametrize('where', ['after_intent', 'after_post'])
def test_actual_sigkill_retains_import_intent_without_automatic_replay(bound, where):
    from app.arr_import_transport import ArrImportHTTP
    report = review(bound); before, revision = bound['store'].load_with_revision()
    pid = os.fork()
    if pid == 0:
        try:
            original = ArrImportHTTP.create
            def die(self, payload):
                if where == 'after_post': original(self, payload)
                os.kill(os.getpid(), signal.SIGKILL)
            ArrImportHTTP.create = die
            apply(bound, report)
        finally: os._exit(99)
    _, status = os.waitpid(pid, 0)
    assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    state, current = bound['store'].load_with_revision()
    assert current == revision + 1 and state[INTENTS_KEY]['kind'] == 'arr_import'
    with pytest.raises(RuntimeError): apply(bound, report)
    assert len(bound['server'].payloads) == (1 if where == 'after_post' else 0)
    if where == 'after_post':
        observed = imports.recover(settings=bound['values'])
        imports.recover(settings=bound['values'], expected_fingerprint=observed['review_fingerprint'])
        assert bound['store'].load_with_revision() == (before, revision + 2)
