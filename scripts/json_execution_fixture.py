"""Disposable JSON execution acceptance. Only explicit new lab roots are used."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
from time import monotonic
import unittest
from urllib.parse import urlsplit

from app.json_move_execution import MoveRequest, execute_move
from app.json_operation_recovery import review_pending_sync, acknowledge_pending_sync
from app.json_scan_control import KEY, initialize_control, scan_attempt
from app.json_tracking_store import JsonTrackingStore
from app.sqlite_arr_title_transport import ArrTitleUpdate, ArrTitleTransportError

NOW = datetime(2026,1,20,12)
SIGNALS = dict(played=True,favorite=False,disliked=True,keep=False,keep_all=False,protected=False)
STATE_PARENT = None
MEDIA_PARENT = None


class JSONExecutionFixtureTests(unittest.TestCase):
    def setUp(self):
        self.state_root = Path(tempfile.mkdtemp(prefix='case-',dir=STATE_PARENT))
        self.media_root = Path(tempfile.mkdtemp(prefix='case-',dir=MEDIA_PARENT))
        self.store = JsonTrackingStore(self.state_root/'state.json')
        state = {key:{} for key in ('first_seen','queued','in_removal','keep_seen','arr_sync_pending')}
        state['first_seen'] = {'Movie':'2026-01-01T01:02:03','TV/Show':'2026-01-02T02:03:04'}
        state['fixture_extension'] = {'retained':'synthetic-only'}
        self.store.path.write_text(json.dumps(state))
        with self.store.session() as session:
            initialize_control(session,previous_started_at=NOW.replace(tzinfo=timezone.utc)-timedelta(hours=2))
        self.requests = {}
        for library,title in (('Movies','Movie'),('TV','Show')):
            source,destination = self.media_root/library,self.media_root/(library+'_hold')
            source.mkdir(); destination.mkdir(); folder=source/title; folder.mkdir()
            media=folder/'video.mkv'; media.write_bytes(b'DISPOSABLE JSON FIXTURE ONLY')
            stamp=datetime(2025,12,1).timestamp(); os.utime(media,(stamp,stamp))
            key=('TV/' if library == 'TV' else '')+title
            self.requests[library]=MoveRequest(library,title,'Waiting','Holding',state['first_seen'][key],30,
                str(source),str(destination),'radarr' if library == 'Movies' else 'sonarr',1 if library == 'Movies' else 2,
                str(folder),str(destination),False)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def respond(self,row,status=200):
                self.send_response(status); self.end_headers(); self.wfile.write(json.dumps(row).encode())
            def do_GET(self):
                self.server.calls.append(('GET',self.path))
                self.respond(self.server.rows[urlsplit(self.path).path])
            def do_PUT(self):
                self.server.calls.append(('PUT',self.path))
                if urlsplit(self.path).query != 'moveFiles=false': return self.respond({},400)
                row=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.server.rows[urlsplit(self.path).path]=row
                if self.server.lost_ack:
                    self.connection.shutdown(socket.SHUT_RDWR); self.connection.close(); return
                self.respond(row,202)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.calls=[]; self.server.lost_ack=False
        self.server.rows={('/api/v3/movie/1' if library == 'Movies' else '/api/v3/series/2'):
            {'id':request.title_id,'path':request.arr_source_path,'monitored':True,
                'seasons':[{'seasonNumber':1,'monitored':True}]}
            for library,request in self.requests.items()}
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def client(self,request,verify=lambda:None):
        return ArrTitleUpdate(service=request.service,base_url='http://127.0.0.1:'+str(self.server.server_port),
            token='synthetic-fixture-token',source_path=request.arr_source_path,title_folder=request.title,verify_binding=verify)

    def execute(self,attempt,request):
        client=self.client(request,attempt.session.verify)
        return execute_move(attempt,request=request,now=NOW,fetch_protection=lambda _:dict(SIGNALS),
            arr_preflight=lambda _:client._request('GET',client._url+'/'+str(request.title_id),monotonic()+10),
            arr_complete=lambda _:client(dict(service=request.service,title_id=request.title_id,
                root=request.arr_destination_root,monitored=request.monitored)))

    def test_movie_and_tv_move_once_with_real_arr_202_and_readbacks(self):
        with scan_attempt(self.store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
            for request in self.requests.values():
                self.assertEqual(self.execute(attempt,request)['status'],'move_and_arr_verified')
                self.assertFalse((Path(request.source_root)/request.title).exists())
                self.assertEqual((Path(request.destination_root)/request.title/'video.mkv').read_bytes(),b'DISPOSABLE JSON FIXTURE ONLY')
            attempt.finish(result='completed')
        result=json.loads(self.store.path.read_bytes())
        self.assertEqual(result['queued'],{'Movie':NOW.isoformat(),'TV/Show':NOW.isoformat()})
        self.assertEqual(result['fixture_extension'],{'retained':'synthetic-only'})
        self.assertIsNone(result[KEY]['journal'])
        self.assertEqual(sum(method == 'PUT' for method,_ in self.server.calls),2)

    def test_lost_sonarr_ack_has_get_only_recovery_without_move_replay(self):
        self.server.lost_ack=True; request=self.requests['TV']
        with self.assertRaises(ArrTitleTransportError):
            with scan_attempt(self.store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
                self.execute(attempt,request)
        before=json.loads(self.store.path.read_bytes())
        self.assertEqual(before[KEY]['journal']['kind'],'arr_sync')
        self.assertEqual(before['queued']['TV/Show'],NOW.isoformat())
        with self.assertRaises(RuntimeError):
            with scan_attempt(self.store,now=(NOW+timedelta(hours=2)).replace(tzinfo=timezone.utc),trigger='manual'): pass
        client=self.client(request)
        def read(req): return client._request('GET',client._url+'/'+str(req.title_id),monotonic()+10)
        reviewed=review_pending_sync(self.store,read_record=read)
        result=acknowledge_pending_sync(self.store,read_record=read,expected_fingerprint=reviewed['review_fingerprint'])
        expected=deepcopy(before); expected[KEY]['journal']=None
        self.assertEqual(json.loads(self.store.path.read_bytes()),expected)
        self.assertEqual(result['arr_updates_sent'],0)
        self.assertEqual(sum(method == 'PUT' for method,_ in self.server.calls),1)

    def test_new_favorite_blocks_disliked_move_before_intent(self):
        request=self.requests['Movies']
        with scan_attempt(self.store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
            with self.assertRaises(RuntimeError):
                execute_move(attempt,request=request,now=NOW,
                    fetch_protection=lambda _:{**SIGNALS,'favorite':True},
                    arr_preflight=lambda _:self.fail('No Arr request expected'),arr_complete=lambda _:self.fail('No update expected'))
        self.assertTrue((Path(request.source_root)/request.title/'video.mkv').exists())
        self.assertFalse(self.server.calls)
        self.assertIsNone(json.loads(self.store.path.read_bytes())[KEY]['journal'])


def main():
    import argparse
    global STATE_PARENT,MEDIA_PARENT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-parent',required=True); parser.add_argument('--media-parent',required=True)
    args=parser.parse_args()
    STATE_PARENT,MEDIA_PARENT=Path(args.state_parent),Path(args.media_parent)
    for parent in (STATE_PARENT,MEDIA_PARENT):
        if not parent.is_absolute() or parent.resolve() != parent or not parent.is_dir() or list(parent.iterdir()):
            raise RuntimeError('Empty canonical disposable lab mounts required')
    if STATE_PARENT == MEDIA_PARENT: raise RuntimeError('Separate new fixture roots required')
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(JSONExecutionFixtureTests))
    if not result.wasSuccessful(): return 1
    print(json.dumps({'status':'json_execution_fixture_verified','tests':result.testsRun,
        'fixture_only':True,'production_services_changed':False,'production_media_mounted':False,
        'external_requests_sent':False,'permanent_deletion_performed':False,
        'lost_ack_get_only_recovery_verified':True,'movie_and_tv_moves_verified':True}))
    return 0


if __name__ == '__main__': raise SystemExit(main())
