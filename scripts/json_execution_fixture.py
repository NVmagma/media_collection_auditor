"""Disposable JSON execution acceptance. Only explicit new lab roots are used."""
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
import tempfile
import threading
from time import monotonic
import unittest
import time
import signal
from urllib.parse import parse_qs
from urllib.parse import urlsplit

from app.json_move_execution import MoveRequest, execute_move
from app.json_operation_recovery import (review_pending_sync, acknowledge_pending_sync,
    review_pending_move, reconcile_pending_move, finish_pending_sync)
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

    def test_sigkill_after_rename_records_move_without_repeating_it(self):
        request=self.requests['TV']
        code = """
import json, os, signal, sys
from datetime import datetime, timezone
from app.json_tracking_store import JsonTrackingStore
from app.json_scan_control import scan_attempt
from app.json_move_execution import MoveRequest, execute_move
import app.json_move_execution as module
request=MoveRequest(**json.loads(sys.argv[2]))
original=module.rename_directory_noreplace_at
def killed(*args):
    original(*args)
    os.kill(os.getpid(),signal.SIGKILL)
module.rename_directory_noreplace_at=killed
with scan_attempt(JsonTrackingStore(sys.argv[1]),now=datetime(2026,1,20,12,tzinfo=timezone.utc),trigger='manual') as attempt:
    execute_move(attempt,request=request,now=datetime(2026,1,20,12),
        fetch_protection=lambda _:dict(played=True,favorite=False,disliked=True,keep=False,keep_all=False,protected=False),
        arr_preflight=lambda _:dict(id=request.title_id,path=request.arr_source_path,monitored=True),
        arr_complete=lambda _:False)
"""
        child=subprocess.run([sys.executable,'-B','-c',code,str(self.store.path),json.dumps(asdict(request))],
            timeout=20,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertEqual(child.returncode,-9,'Synthetic child must die at the rename boundary')
        before=json.loads(self.store.path.read_bytes())
        self.assertEqual(before[KEY]['journal']['kind'],'move')
        self.assertIn('TV/Show',before['first_seen'])
        self.assertFalse((Path(request.source_root)/request.title).exists())
        self.assertTrue((Path(request.destination_root)/request.title/'video.mkv').is_file())
        client=self.client(request)
        def read(req): return client._request('GET',client._url+'/'+str(req.title_id),monotonic()+10)
        review=review_pending_move(self.store,read_record=read)
        self.assertEqual(review['physical_location'],'destination')
        reconcile_pending_move(self.store,read_record=read,expected_fingerprint=review['review_fingerprint'])
        moved=json.loads(self.store.path.read_bytes())
        self.assertEqual(moved['queued']['TV/Show'],NOW.isoformat())
        self.assertNotIn('TV/Show',moved['first_seen'])
        self.assertEqual(moved[KEY]['last_started_at'],before[KEY]['last_started_at'])
        self.assertFalse(any(method == 'PUT' for method,_ in self.server.calls))
        sync=review_pending_sync(self.store,read_record=read)
        result=finish_pending_sync(self.store,read_record=read,
            expected_fingerprint=sync['review_fingerprint'],send_update=lambda req:client(dict(
                service=req.service,title_id=req.title_id,root=req.arr_destination_root,monitored=req.monitored)))
        self.assertEqual(result['arr_update_attempts'],1)
        self.assertIsNone(json.loads(self.store.path.read_bytes())[KEY]['journal'])
        self.assertEqual(sum(method == 'PUT' for method,_ in self.server.calls),1)
        self.assertEqual((Path(request.destination_root)/request.title/'video.mkv').read_bytes(),b'DISPOSABLE JSON FIXTURE ONLY')

    def test_actual_entrypoint_manual_scan_settings_and_restart(self):
        import requests
        from app.config_store import KEYS,DEFAULTS
        all_requests={library:[request] for library,request in self.requests.items()}
        with self.store.session() as state:
            for library,template in self.requests.items():
                resource='series' if library=='TV' else 'movie'
                for index in range(1,6):
                    title=template.title+' '+str(index); folder=Path(template.source_root)/title
                    folder.mkdir(); media=folder/'video.mkv'; media.write_bytes(b'DISPOSABLE JSON SERVICE FIXTURE')
                    old=datetime(2025,12,1).timestamp(); os.utime(media,(old,old))
                    req=replace(template,title=title,title_id=(20 if library=='TV' else 10)+index,arr_source_path=str(folder))
                    all_requests[library].append(req)
                    state.state['first_seen'][('TV/' if library=='TV' else '')+title]=template.source_since
                    self.server.rows['/api/v3/'+resource+'/'+str(req.title_id)]=dict(id=req.title_id,path=req.arr_source_path,monitored=True,
                        seasons=[{'seasonNumber':1,'monitored':True}])
            state.checkpoint()
        handler=self.server.RequestHandlerClass
        original_get=handler.do_GET
        def get(handler):
            url=urlsplit(handler.path)
            if url.path=='/Users': return handler.respond([{'Id':'fixture-user'}])
            if url.path.endswith('/Items'):
                query=parse_qs(url.query); kind=query.get('IncludeItemTypes',['Movie'])[0]
                library='TV' if kind=='Series' else 'Movies'
                rows=[dict(Id='fixture-'+library+str(req.title_id),Type=kind,Name=req.title,Path=req.arr_source_path+('/video.mkv' if library=='Movies' else ''),
                    Tags=['not-at-all'],UserData=dict(Played=True,PlayCount=1,IsFavorite=False)) for req in all_requests[library]]
                start=int(query.get('StartIndex',['0'])[0]); limit=int(query.get('Limit',['100'])[0])
                return handler.respond(dict(Items=rows[start:start+limit],TotalRecordCount=len(rows),StartIndex=start))
            return original_get(handler)
        handler.do_GET=get
        for library,resource,id_ in (('Movies','movie',1),('TV','series',2)):
            self.server.rows['/api/v3/'+resource]=[deepcopy(self.server.rows['/api/v3/'+resource+'/'+str(req.title_id)]) for req in all_requests[library]]
            for suffix in ('_keep','_removal'): (self.media_root/(library+suffix)).mkdir()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        base='http://127.0.0.1:'+str(port); remote='http://127.0.0.1:'+str(self.server.server_port)
        token='synthetic-json-service-integration-token'
        values=dict(STATE_FILE=str(self.store.path),AUDITOR_STATE_BACKEND='json',AUDITOR_WORKER_MODE='json_serialized',
            DRY_RUN='false',MAX_ACTIONS_PER_RUN='10',ENABLE_MOVIES='true',ENABLE_TV='true',TZ='UTC',
            SQLITE_DAILY_RUN_TIME=(datetime.now(timezone.utc)+timedelta(minutes=2)).strftime('%H:%M'),
            SQLITE_DAILY_RUN_TIMEZONE='UTC',WEB_PORT=str(port),WEB_SESSION_SECRET='synthetic-json-fixture-session',
            WEB_ADMIN_USER='fixture-admin',WEB_ADMIN_PASSWORD='fixture-password',INTEGRATION_API_TOKEN=token,
            WEB_CONFIG_FILE=str(self.state_root/'config.json'),AUDIT_HISTORY_FILE=str(self.state_root/'history.jsonl'),
            JELLYFIN_HOST_URL=remote,JELLYFIN_API_TOKEN='synthetic-jellyfin-token',
            RADARR_URL=remote,SONARR_URL=remote,RADARR_API_KEY='synthetic-arr-token',SONARR_API_KEY='synthetic-arr-token')
        for library,prefix in (('Movies','RADARR'),('TV','SONARR')):
            for field,suffix in (('TRANSIENT',''),('HOLDING','_hold'),('KEEP','_keep'),('REMOVAL','_removal')):
                values[prefix+'_'+field+'_PATH']=str(self.media_root/(library+suffix))
        process=None
        session=requests.Session(); session.trust_env=False
        def start():
            nonlocal process
            child_env={**os.environ,**values}
            packaged=os.environ.get('JSON_FIXTURE_PACKAGED_APP') == 'true'
            if packaged: child_env['PYTHONPATH']='/app/app:/app'
            process=subprocess.Popen([sys.executable,'-B','-m','app.main'],env=child_env,
                cwd='/app' if packaged else None,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            for _ in range(200):
                if process.poll() is not None: raise AssertionError('Synthetic JSON service stopped before readiness')
                try:
                    if session.get(base+'/health',timeout=1).status_code==200: return
                except requests.RequestException: pass
                time.sleep(.05)
            raise AssertionError('Synthetic JSON service readiness expired')
        def stop():
            if process is not None and process.poll() is None:
                process.send_signal(signal.SIGINT)
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5); raise
        def login():
            response=session.post(base+'/login',data=dict(username='fixture-admin',password='fixture-password'),
                headers={'Origin':base},allow_redirects=False,timeout=10)
            self.assertEqual(response.status_code,302)
        headers={'Authorization':'Bearer '+token}
        try:
            start(); login(); original=self.store.path.read_bytes()
            page=session.get(base+'/settings',timeout=10)
            self.assertEqual(page.status_code,200); self.assertIn('Apply Requested Settings',page.text)
            self.assertNotIn('Type I UNDERSTAND',page.text)
            self.assertEqual(self.store.path.read_bytes(),original)
            response=session.post(base+'/api/run-now',json={'run_live_scan':True},headers={'Origin':base},timeout=10)
            self.assertEqual(response.status_code,202)
            for _ in range(300):
                report=session.get(base+'/api/v1/audit-status',headers=headers,timeout=3).json()
                if report['last_finished'] and not report['running']: break
                time.sleep(.05)
            else: self.fail('Synthetic manual scan did not finish')
            self.assertEqual(report['last_result'],'completed')
            self.assertEqual(report['per_library_action_limit'],5)
            state=json.loads(self.store.path.read_bytes())
            self.assertEqual(len(state['queued']),10)
            self.assertEqual(sum(key.startswith('TV/') for key in state['queued']),5)
            self.assertEqual(len(state['first_seen']),2)
            self.assertEqual(sum(method=='PUT' for method,_ in self.server.calls),10)
            history=session.get(base+'/api/v1/scan-history',headers=headers,timeout=10)
            self.assertEqual(history.status_code,200); self.assertTrue(history.json()['history_persistent'])
            form={key:values.get(key,DEFAULTS.get(key,'')) for key in KEYS}
            form.update(settings_action='apply',ENABLE_TV='false',HOLDING_DAYS='8')
            response=session.post(base+'/settings',data=form,headers={'Origin':base},allow_redirects=False,timeout=10)
            self.assertEqual(response.status_code,302)
            saved=json.loads((self.state_root/'config.json').read_bytes())
            self.assertEqual(saved['ENABLE_TV'],'false'); self.assertEqual(saved['HOLDING_DAYS'],'8')
            unchanged=self.store.path.read_bytes()
            stop(); start(); login()
            report=session.get(base+'/api/v1/audit-status',headers=headers,timeout=5).json()
            self.assertEqual(report['last_result'],'completed'); self.assertTrue(report['history_persistent'])
            response=session.post(base+'/api/run-now',json={'run_live_scan':True},headers={'Origin':base},timeout=10)
            self.assertEqual(response.status_code,429)
            self.assertEqual(self.store.path.read_bytes(),unchanged)
            self.assertEqual(sum(method=='PUT' for method,_ in self.server.calls),10)
        finally:
            stop(); session.close()

    def test_private_cutover_cli_copies_latest_state_and_claims_without_starting_service(self):
        import base64,hashlib
        from scripts.unraid_live_update_backup import capture_backup
        source=self.store.path.read_bytes(); snapshot=json.loads(source); snapshot.pop(KEY)
        packet=self.state_root/'backup'; packet.mkdir(mode=0o700)
        destination=self.state_root/'prepared'; destination.mkdir(mode=0o700)
        start=NOW.replace(tzinfo=timezone.utc)-timedelta(minutes=20)
        claim=dict(schema_version=2,phase='slot_claimed',timezone='UTC',local_date=start.date().isoformat(),
            automatic_replay=False,trigger='manual',scheduled_at=start.isoformat(),started_at=start.isoformat())
        name=hashlib.sha256(('manual-live\0UTC\0'+start.isoformat()).encode()).hexdigest()+'.json'
        claims=dict(present=True,entries={name:base64.b64encode(json.dumps(claim).encode()).decode()})
        current=dict(Name='/media_collection_auditor',Id='a'*64,Image='sha256:'+'b'*64,
            Config=dict(Env=['DRY_RUN=false','MAX_ACTIONS_PER_RUN=2','TZ=UTC','SQLITE_DAILY_RUN_TIMEZONE=UTC']))
        inputs={key:(raw,(1,index)) for index,(key,raw) in enumerate((
            ('saved-config.json',b'{"ENABLE_TV":"true","private_extension":"retained"}'),
            ('retained-source.json',b'{"old_source":"retained"}'),('current-binding.json',b'{"old_binding":"retained"}')))}
        info=packet.stat(); selected=(info.st_dev,info.st_ino)
        capture_backup(directory=packet,expected_identity=selected,container=current,template=b'<Container/>',
            source_revision='c'*40,validate_current=lambda:None,read_snapshot=lambda:(deepcopy(snapshot),7),
            read_inputs=lambda:deepcopy(inputs),read_claims=lambda:(deepcopy(claims),('synthetic',1)))
        fingerprint=hashlib.sha256((packet/'backup-complete.json').read_bytes()).hexdigest()
        image=dict(Id='sha256:'+'d'*64,Config=dict(Labels={
            'org.opencontainers.image.revision':'e'*40,'io.media-collection-auditor.worker':'json-serialized'},
            Entrypoint=['python','-B','-m','app.main'],Cmd=None,Volumes=None,StopSignal='SIGINT',
            Env=['AUDITOR_WORKER_MODE=json_serialized','AUDITOR_STATE_BACKEND=json','DRY_RUN=true','MAX_ACTIONS_PER_RUN=10']))
        info=destination.stat()
        result=subprocess.run([sys.executable,'-B','-m','scripts.json_cutover_prepare',
            '--backup',str(packet),'--backup-identity',str(selected[0])+':'+str(selected[1]),
            '--fingerprint',fingerprint,'--root',str(destination),
            '--root-identity',str(info.st_dev)+':'+str(info.st_ino),'--revision','e'*40,
            '--original-container-id',current['Id']],input=json.dumps([image]).encode(),
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
        self.assertEqual(result.returncode,0,'Synthetic private preparation must succeed')
        report=json.loads(result.stdout)
        self.assertEqual(report['status'],'json_replacement_prepared_not_started')
        self.assertFalse(report['deployment_authorized']); self.assertEqual(report['per_library_action_limit'],5)
        migrated=json.loads((destination/'logs/auditor_state.json').read_bytes())
        self.assertEqual(migrated[KEY]['last_started_at'],start.isoformat()); migrated.pop(KEY)
        self.assertEqual(migrated,snapshot)
        self.assertEqual((destination/'scan-claims-archive.json').read_bytes(),(packet/'daily-claims.json').read_bytes())
        self.assertEqual(self.store.path.read_bytes(),source); self.assertFalse(self.server.calls)

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
        'lost_ack_get_only_recovery_verified':True,'sigkill_move_recovery_verified':True,'actual_json_service_verified':True,'five_moves_per_library_verified':True,'private_preparation_cli_verified':True,'packaged_entrypoint_verified':os.environ.get('JSON_FIXTURE_PACKAGED_APP') == 'true','movie_and_tv_moves_verified':True}))
    return 0


if __name__ == '__main__': raise SystemExit(main())
