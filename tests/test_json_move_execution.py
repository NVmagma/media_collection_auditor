"""Test JSON moves with temporary folders and local Arr updates."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from time import monotonic
from urllib.parse import urlsplit

import pytest
from app.json_move_execution import MoveRequest, execute_move
from app.json_scan_control import KEY, initialize_control, scan_attempt
from app.json_tracking_store import JsonTrackingStore
from app.arr_title_transport import ArrTitleUpdate, ArrTitleTransportError
from test_json_tracking_store import state

NOW = datetime(2026,1,20,12)
SIG = dict(played=True,favorite=False,disliked=True,keep=False,keep_all=False,protected=False)


@pytest.fixture
def move_case(tmp_path):
    store = JsonTrackingStore(tmp_path/'state.json'); store.path.write_text(json.dumps(state()))
    with store.session() as session: initialize_control(session,previous_started_at=NOW.replace(tzinfo=timezone.utc)-timedelta(hours=2))
    roots,requests = {},{}
    for library,title in (('Movies','Movie'),('TV','Show')):
        source,destination = tmp_path/library,tmp_path/(library+'_hold'); source.mkdir(); destination.mkdir()
        folder = source/title; folder.mkdir(); media = folder/'video.mkv'; media.write_bytes(b'disposable-media')
        stamp = datetime(2025,12,1).timestamp(); os.utime(media,(stamp,stamp))
        roots[library] = source,destination
        key = ('TV/' if library == 'TV' else '')+title
        requests[library] = MoveRequest(library,title,'Waiting','Holding',state()['first_seen'][key],30,
            str(source),str(destination),'radarr' if library == 'Movies' else 'sonarr',1 if library == 'Movies' else 2,
            str(folder),str(destination),False)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a): pass
        def respond(self,row,status=200):
            self.send_response(status); self.end_headers(); self.wfile.write(json.dumps(row).encode())
        def do_GET(self):
            self.server.calls.append(('GET',self.path))
            return self.respond(self.server.records[urlsplit(self.path).path])
        def do_PUT(self):
            self.server.calls.append(('PUT',self.path))
            assert urlsplit(self.path).query == 'moveFiles=false'
            row = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.server.records[urlsplit(self.path).path] = row
            if self.server.mode == 'lost_ack':
                self.connection.shutdown(socket.SHUT_RDWR); self.connection.close(); return
            return self.respond(row,202)
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.calls,server.mode = [],'normal'
    server.records = {('/api/v3/movie/1' if lib == 'Movies' else '/api/v3/series/2'):
        {'id':req.title_id,'path':req.arr_source_path,'monitored':True,
         'seasons':[{'seasonNumber':1,'monitored':True}],'private':'synthetic-private-resource'}
        for lib,req in requests.items()}
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try: yield store,roots,requests,server
    finally: server.shutdown(); server.server_close(); thread.join()


def transports(attempt,request,server):
    client = ArrTitleUpdate(service=request.service,base_url='http://127.0.0.1:'+str(server.server_port),
        token='synthetic-token',source_path=request.arr_source_path,title_folder=request.title,
        verify_binding=attempt.session.verify)
    def preflight(_):
        return client._request('GET',client._url+'/'+str(request.title_id),monotonic()+10)
    def complete(_):
        return client({'service':request.service,'title_id':request.title_id,
            'root':request.arr_destination_root,'monitored':request.monitored})
    return preflight,complete


def test_moves_one_movie_and_one_show_with_real_put_and_readbacks(move_case):
    store,roots,requests,server = move_case
    before=json.loads(store.path.read_bytes())
    with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
        for lib,request in requests.items():
            preflight,complete=transports(attempt,request,server)
            result=execute_move(attempt,request=request,now=NOW,fetch_protection=lambda _:dict(SIG),
                arr_preflight=preflight,arr_complete=complete)
            assert result['status'] == 'move_and_arr_verified'
            assert not result['permanent_deletion_performed']
            assert not (roots[lib][0]/request.title).exists()
            assert (roots[lib][1]/request.title/'video.mkv').read_bytes() == b'disposable-media'
        attempt.finish(result='completed')
    current=json.loads(store.path.read_bytes())
    assert current['first_seen'] == {}
    assert current['queued'] == {'Movie':NOW.isoformat(),'TV/Show':NOW.isoformat()}
    assert current['unknown'] == before['unknown'] and current[KEY]['journal'] is None
    assert sum(method == 'PUT' for method,_ in server.calls) == 2
    for resource,id_ in (('movie',1),('series',2)):
        assert sum(method == 'GET' and path == f'/api/v3/{resource}/{id_}' for method,path in server.calls) == 4
        assert server.records[f'/api/v3/{resource}/{id_}']['seasons'] == [{'seasonNumber':1,'monitored':True}]


def test_lost_arr_ack_preserves_new_clock_and_pending_intent(move_case):
    store,roots,requests,server = move_case; server.mode='lost_ack'; request=requests['TV']
    with pytest.raises(ArrTitleTransportError):
        with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
            preflight,complete=transports(attempt,request,server)
            execute_move(attempt,request=request,now=NOW,fetch_protection=lambda _:dict(SIG),arr_preflight=preflight,arr_complete=complete)
    current=json.loads(store.path.read_bytes())
    assert current['queued']['TV/Show'] == NOW.isoformat() and 'TV/Show' not in current['first_seen']
    assert current[KEY]['journal']['kind'] == 'arr_sync'
    assert (roots['TV'][1]/'Show'/'video.mkv').exists()
    with pytest.raises(RuntimeError):
        with scan_attempt(store,now=(NOW+timedelta(hours=2)).replace(tzinfo=timezone.utc),trigger='manual'): pass
    assert sum(method == 'PUT' for method,_ in server.calls) == 1


def test_changed_protection_and_occupied_destination_never_move_or_put(move_case):
    store,roots,requests,server=move_case; request=requests['Movies']
    with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
        with pytest.raises(RuntimeError):
            execute_move(attempt,request=request,now=NOW,
                fetch_protection=lambda _:{**SIG,'protected':True,'keep_all':True},
                arr_preflight=lambda _:pytest.fail('Protection changed'),arr_complete=lambda _:pytest.fail('No PUT'))
        (roots['Movies'][1]/'Movie').mkdir()
        with pytest.raises(RuntimeError):
            execute_move(attempt,request=request,now=NOW,fetch_protection=lambda _:dict(SIG),
                arr_preflight=lambda _:pytest.fail('Destination occupied'),arr_complete=lambda _:pytest.fail('No PUT'))
    assert (roots['Movies'][0]/'Movie'/'video.mkv').exists() and not server.calls
    assert json.loads(store.path.read_bytes())[KEY]['journal'] is None


@pytest.mark.parametrize('phase',['after_rename','before_arr'])
def test_actual_sigkill_retains_exact_operation_without_replay(move_case,phase):
    store,roots,requests,server=move_case; request=requests['Movies']
    code='''import json, os, signal, sys
from datetime import datetime, timezone
from app.json_tracking_store import JsonTrackingStore
from app.json_scan_control import scan_attempt
from app.json_move_execution import MoveRequest
import app.json_move_execution as module
path, raw, phase = sys.argv[1:]
request=MoveRequest(**json.loads(raw)); now=datetime(2026,1,20,12)
if phase == "after_rename":
 original=module.rename_directory_noreplace_at
 def rename(*args):
  original(*args); os.kill(os.getpid(),signal.SIGKILL)
 module.rename_directory_noreplace_at=rename
with scan_attempt(JsonTrackingStore(path),now=now.replace(tzinfo=timezone.utc),trigger="manual") as attempt:
 module.execute_move(attempt,request=request,now=now,
  fetch_protection=lambda _:dict(played=True,favorite=False,disliked=True,keep=False,keep_all=False,protected=False),
  arr_preflight=lambda _:dict(id=request.title_id,path=request.arr_source_path,monitored=True),
  arr_complete=lambda _:os.kill(os.getpid(),signal.SIGKILL))
'''
    result=subprocess.run([sys.executable,'-B','-c',code,str(store.path),json.dumps(asdict(request)),phase],timeout=20)
    assert result.returncode == -9
    current=json.loads(store.path.read_bytes())
    assert current[KEY]['journal']['kind'] == ('move' if phase == 'after_rename' else 'arr_sync')
    assert (roots['Movies'][1]/'Movie'/'video.mkv').exists()
    if phase == 'after_rename': assert current['first_seen']['Movie'] == request.source_since
    else: assert current['queued']['Movie'] == NOW.isoformat()
    with pytest.raises(RuntimeError):
        with scan_attempt(store,now=(NOW+timedelta(hours=2)).replace(tzinfo=timezone.utc),trigger='manual'): pass
    assert not server.calls


def test_one_action_per_library_cannot_be_bypassed_by_second_move(move_case):
    store,roots,requests,server=move_case; request=requests['Movies']
    with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
        preflight,complete=transports(attempt,request,server)
        execute_move(attempt,request=request,now=NOW,fetch_protection=lambda _:dict(SIG),arr_preflight=preflight,arr_complete=complete)
        with pytest.raises(RuntimeError,match='slot'):
            execute_move(attempt,request=replace(request,title='Other',arr_source_path=request.source_root+'/Other'),now=NOW,
                fetch_protection=lambda _:pytest.fail('Excluded title fetched'),
                arr_preflight=lambda _:pytest.fail('Excluded title fetched'),arr_complete=lambda _:pytest.fail('Excluded title sent'))
    assert sum(method == 'PUT' for method,_ in server.calls) == 1


def test_explicit_get_only_recovery_clears_lost_ack_without_second_put(move_case):
    from app.json_operation_recovery import review_pending_sync, acknowledge_pending_sync
    store,roots,requests,server=move_case; server.mode='lost_ack'; request=requests['TV']
    with pytest.raises(ArrTitleTransportError):
        with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
            preflight,complete=transports(attempt,request,server)
            execute_move(attempt,request=request,now=NOW,fetch_protection=lambda _:dict(SIG),arr_preflight=preflight,arr_complete=complete)
    before=json.loads(store.path.read_bytes())
    client=ArrTitleUpdate(service='sonarr',base_url='http://127.0.0.1:'+str(server.server_port),
        token='synthetic-token',source_path=request.arr_source_path,title_folder=request.title)
    def read(req): return client._request('GET',client._url+'/'+str(req.title_id),monotonic()+10)
    report=review_pending_sync(store,read_record=read)
    assert json.loads(store.path.read_bytes()) == before
    result=acknowledge_pending_sync(store,read_record=read,expected_fingerprint=report['review_fingerprint'])
    expected=deepcopy(before); expected[KEY]['journal']=None
    assert json.loads(store.path.read_bytes()) == expected
    assert result['tracking_clocks_preserved'] and result['arr_updates_sent'] == 0
    assert not result['historical_completion_recorded']
    assert sum(method == 'PUT' for method,_ in server.calls) == 1


def test_stale_recovery_fingerprint_never_clears_pending_sync(move_case):
    from app.json_operation_recovery import review_pending_sync, acknowledge_pending_sync
    store,roots,requests,server=move_case; request=requests['Movies']; server.mode='lost_ack'
    with pytest.raises(ArrTitleTransportError):
        with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
            preflight,complete=transports(attempt,request,server)
            execute_move(attempt,request=request,now=NOW,fetch_protection=lambda _:dict(SIG),arr_preflight=preflight,arr_complete=complete)
    read=lambda req:deepcopy(server.records['/api/v3/movie/1'])
    report=review_pending_sync(store,read_record=read)
    with store.session() as session:
        session.state['unknown']['new']='retained'; session.checkpoint()
    before=store.path.read_bytes()
    with pytest.raises(RuntimeError):
        acknowledge_pending_sync(store,read_record=read,expected_fingerprint=report['review_fingerprint'])
    assert store.path.read_bytes() == before


def test_destination_race_never_overwrites_or_sends_arr_update(move_case,monkeypatch):
    import app.json_move_execution as module
    store,roots,requests,server=move_case; request=requests['Movies']
    original=module.rename_directory_noreplace_at
    def collide(*args):
        target=Path(request.destination_root)/request.title; target.mkdir()
        (target/'retained.txt').write_text('external destination')
        return original(*args)
    monkeypatch.setattr(module,'rename_directory_noreplace_at',collide)
    with pytest.raises(FileExistsError):
        with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
            preflight,complete=transports(attempt,request,server)
            execute_move(attempt,request=request,now=NOW,fetch_protection=lambda _:dict(SIG),arr_preflight=preflight,arr_complete=complete)
    assert (Path(request.source_root)/request.title/'video.mkv').exists()
    assert (Path(request.destination_root)/request.title/'retained.txt').read_text() == 'external destination'
    assert not any(method == 'PUT' for method,_ in server.calls)
    current=json.loads(store.path.read_bytes())
    assert current['first_seen']['Movie'] == request.source_since and current[KEY]['journal']['kind'] == 'move'


def test_failed_post_move_checkpoint_never_sends_arr_put(move_case,monkeypatch):
    store,roots,requests,server=move_case; request=requests['Movies']; original=os.replace
    with pytest.raises(OSError):
        with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
            def fail(*args,**kwargs):
                journal=attempt.session.state[KEY]['journal']
                if journal is not None and journal['kind'] == 'arr_sync': raise OSError('synthetic interrupted save')
                return original(*args,**kwargs)
            monkeypatch.setattr(os,'replace',fail)
            preflight,complete=transports(attempt,request,server)
            execute_move(attempt,request=request,now=NOW,fetch_protection=lambda _:dict(SIG),arr_preflight=preflight,arr_complete=complete)
    assert (Path(request.destination_root)/request.title/'video.mkv').exists()
    assert not any(method == 'PUT' for method,_ in server.calls)
    current=json.loads(store.path.read_bytes())
    assert current[KEY]['journal']['kind'] == 'move' and current['first_seen']['Movie'] == request.source_since
