"""Test the JSON worker using only new, temporary test folders."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
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
import shutil
from urllib.parse import parse_qs
from urllib.parse import urlsplit

from app.json_move_execution import MoveRequest, execute_move
from app.json_operation_recovery import (review_pending_sync, acknowledge_pending_sync,
    review_pending_move, reconcile_pending_move, finish_pending_sync)
from app.json_scan_control import KEY, initialize_control, scan_attempt
from app.json_tracking_store import JsonTrackingStore
from app.arr_title_transport import ArrTitleUpdate, ArrTitleTransportError

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
                record=self.server.rows.get(urlsplit(self.path).path)
                self.respond(record,200 if record is not None else 404)
            def do_DELETE(self):
                self.server.calls.append(('DELETE',self.path))
                resource=urlsplit(self.path).path;query=parse_qs(urlsplit(self.path).query)
                expected='addImportExclusion' if resource.startswith('/api/v3/movie/') else 'addImportListExclusion'
                if query!={'deleteFiles':['true'],expected:['true']}: return self.respond({},400)
                row=self.server.rows.pop(resource)
                target=Path(row['path'])
                if self.server.media_root not in target.resolve().parents: raise RuntimeError('Fixture target outside disposable media')
                shutil.rmtree(target)
                if self.server.lost_ack:
                    self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                self.respond({},200)
            def do_PUT(self):
                self.server.calls.append(('PUT',self.path))
                if urlsplit(self.path).query != 'moveFiles=false': return self.respond({},400)
                row=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.server.rows[urlsplit(self.path).path]=row
                if self.server.lost_ack:
                    self.connection.shutdown(socket.SHUT_RDWR); self.connection.close(); return
                self.respond(row,202)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.media_root=self.media_root
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
            DAILY_RUN_TIME=(datetime.now(timezone.utc)+timedelta(hours=1)).strftime('%H:%M'),
            DAILY_RUN_TIMEZONE='UTC',WEB_PORT=str(port),WEB_SESSION_SECRET='synthetic-json-fixture-session',
            WEB_ADMIN_USER='fixture-admin',WEB_ADMIN_PASSWORD='fixture-password',INTEGRATION_API_TOKEN=token,
            WEB_CONFIG_FILE=str(self.state_root/'config.json'),AUDIT_HISTORY_FILE=str(self.state_root/'history.jsonl'),
            JELLYFIN_HOST_URL=remote,JELLYFIN_API_TOKEN='synthetic-jellyfin-token',
            RADARR_URL=remote,SONARR_URL=remote,RADARR_API_KEY='synthetic-arr-token',SONARR_API_KEY='synthetic-arr-token')
        for library,prefix in (('Movies','RADARR'),('TV','SONARR')):
            for field,suffix in (('TRANSIENT',''),('HOLDING','_hold'),('KEEP','_keep'),('REMOVAL','_removal')):
                values[prefix+'_'+field+'_PATH']=str(self.media_root/(library+suffix))
        (self.state_root/'config.json').write_bytes(b'{}')
        (self.state_root/'config.json').chmod(0o600)
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
        stale_title = 'Missing Fixture Movie'
        stale_clock = '2026-01-03T03:04:05'
        with self.store.session() as tracking:
            tracking.state['first_seen'][stale_title] = stale_clock
            tracking.checkpoint()
        archive_url = base + '/tracking-review/archive'
        archive_history_url = archive_url + '/history'
        archive_selection = {'library': 'Movies', 'title': stale_title}
        origin = {'Origin': base}
        try:
            start()
            from app.runtime_readiness import health_contract
            self.assertEqual(session.get(base+'/login',timeout=5).status_code,200)
            for route in ('/api/v1/summary','/api/v1/audit-status'):
                self.assertEqual(session.get(base+route,timeout=5).status_code,401)
            for _ in range(100):
                initial_audit=session.get(base+'/api/v1/audit-status',headers=headers,timeout=5).json()
                if initial_audit.get('next_run'): break
                time.sleep(.02)
            initial_state=json.loads(self.store.path.read_bytes())
            health_contract(session.get(base+'/api/v1/summary',headers=headers,timeout=5).json(),initial_audit,
                {key:len(initial_state.get(key,{})) for key in ('first_seen','queued','in_removal','keep_seen','arr_sync_pending')})
            login()
            before_archive = self.store.path.read_bytes()
            calls_before_archive = list(self.server.calls)
            reviewed = session.post(archive_url, params=archive_selection,
                                    data={'action': 'review'}, headers=origin, timeout=5)
            self.assertEqual(reviewed.status_code, 200)
            fingerprint = re.search(r'name="fingerprint" value="([0-9a-f]{64})"', reviewed.text)
            self.assertIsNotNone(fingerprint)
            self.assertEqual(self.store.path.read_bytes(), before_archive)
            archived = session.post(archive_url, params=archive_selection,
                                    data={'action': 'archive', 'fingerprint': fingerprint.group(1)},
                                    headers=origin, timeout=5)
            self.assertEqual(archived.status_code, 200)
            self.assertIn('Archived the Waiting clock', archived.text)
            original = self.store.path.read_bytes()
            archived_state = json.loads(original)
            self.assertNotIn(stale_title, archived_state['first_seen'])
            self.assertEqual(archived_state['archived_tracking_clocks'][stale_title]['timestamp'], stale_clock)
            self.assertEqual(self.server.calls, calls_before_archive)
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
            activity=session.get(base+'/logs',timeout=10)
            self.assertEqual(activity.status_code,200); self.assertIn('Verified moves: 10',activity.text)
            exported=session.get(base+'/logs/export',timeout=10)
            self.assertEqual(exported.status_code,200)
            self.assertIn('Verified moves: 10',exported.text)
            self.assertNotIn('synthetic-arr-token',exported.text)
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
            self.assertIn('Verified moves: 10',session.get(base+'/logs',timeout=10).text)
            response=session.post(base+'/api/run-now',json={'run_live_scan':True},headers={'Origin':base},timeout=10)
            self.assertEqual(response.status_code,429)
            self.assertEqual(self.store.path.read_bytes(),unchanged)
            self.assertEqual(sum(method=='PUT' for method,_ in self.server.calls),10)
            config_path=self.state_root/'config.json'; valid_config=config_path.read_bytes()
            # Broken saved preview settings must not select the live ENV fallback.
            preview_config=json.loads(valid_config); preview_config['DRY_RUN']='true'
            config_path.write_text(json.dumps(preview_config)); config_path.write_bytes(b'{')
            response=session.post(base+'/api/run-now',json={'run_live_scan':True},headers={'Origin':base},timeout=10)
            self.assertEqual(response.status_code,409)
            self.assertEqual(session.get(base+'/health',timeout=5).status_code,200)
            paused_page=session.get(base+'/settings',timeout=5)
            self.assertEqual(paused_page.status_code,200); self.assertIn('scans remain paused',paused_page.text)
            self.assertTrue(session.get(base+'/api/v1/audit-status',headers=headers,timeout=5).json()['execution_blocked'])
            config_path.unlink()
            self.assertEqual(session.post(base+'/api/run-now',json={'run_live_scan':True},headers={'Origin':base},timeout=5).status_code,409)
            config_path.write_bytes(valid_config); config_path.chmod(0o600)
            self.assertEqual(self.store.path.read_bytes(),unchanged)
            self.assertEqual(sum(method=='PUT' for method,_ in self.server.calls),10)
            # Exercise the browser backup workflow, then boot the disposable copy.
            source_history = Path(values['AUDIT_HISTORY_FILE'])
            original_history = source_history.read_bytes()
            calls_before_recovery = list(self.server.calls)
            backup_page = session.get(base + '/backups', timeout=5)
            self.assertEqual(backup_page.status_code, 200)
            csrf = re.search(r'name="csrf" value="([A-Za-z0-9_-]+)"', backup_page.text)
            self.assertIsNotNone(csrf)
            form = {'csrf': csrf.group(1)}
            created = session.post(base + '/backups', data={**form, 'action': 'create'},
                                   headers=origin, timeout=10)
            self.assertEqual(created.status_code, 200)
            self.assertIn('backup created and verified', created.text)
            packet = re.search(r'name="identifier" value="([0-9a-f]{32})"', created.text)
            self.assertIsNotNone(packet)
            copied = session.post(base + '/backups', data={**form, 'action': 'test_restore',
                                  'identifier': packet.group(1)}, headers=origin, timeout=10)
            self.assertEqual(copied.status_code, 200)
            test_copy = re.search(r'Reference: ([0-9a-f]{32})', copied.text)
            self.assertIsNotNone(test_copy)
            restored = self.state_root / '.auditor-backups' / '.restore-tests' / test_copy.group(1)
            restored_state = restored / 'auditor_state.json'
            restored_config = restored / 'saved-config.json'
            self.assertEqual(restored_state.read_bytes(), unchanged)
            self.assertEqual(restored_config.read_bytes(), valid_config)

            stop()
            values.update(STATE_FILE=str(restored_state), WEB_CONFIG_FILE=str(restored_config),
                          AUDIT_HISTORY_FILE=str(restored / 'history.jsonl'))
            start()
            login()
            for _ in range(100):
                audit = session.get(base + '/api/v1/audit-status', headers=headers, timeout=5).json()
                if audit.get('next_run'):
                    break
                time.sleep(.02)
            summary = session.get(base + '/api/v1/summary', headers=headers, timeout=5)
            self.assertEqual(summary.status_code, 200)
            health_contract(summary.json(), audit, {key: len(state[key]) for key in
                            ('first_seen', 'queued', 'in_removal', 'keep_seen', 'arr_sync_pending')})
            self.assertIsNone(audit.get('last_result'))
            history_page = session.get(archive_history_url, params={'q': stale_title}, timeout=5)
            self.assertEqual(history_page.status_code, 200)
            self.assertIn('1 matching clocks', history_page.text)
            self.assertIn(stale_title, history_page.text)
            self.assertIn(stale_clock, history_page.text)
            self.assertNotIn(stale_title, json.loads(restored_state.read_bytes())['first_seen'])
            settings_page = session.get(base + '/settings', timeout=5)
            self.assertEqual(settings_page.status_code, 200)
            self.assertRegex(settings_page.text, r'name="HOLDING_DAYS"[^>]*value="8"')
            cooldown = session.post(base + '/api/run-now', json={'run_live_scan': True},
                                    headers=origin, timeout=5)
            self.assertEqual(cooldown.status_code, 429)
            stop()
            self.assertEqual(restored_state.read_bytes(), unchanged)
            self.assertEqual(restored_config.read_bytes(), valid_config)
            self.assertEqual(self.store.path.read_bytes(), unchanged)
            self.assertEqual(config_path.read_bytes(), valid_config)
            self.assertEqual(source_history.read_bytes(), original_history)
            self.assertEqual(self.server.calls, calls_before_recovery)
        finally:
            stop(); session.close()


    def test_packaged_orphan_quarantine_detects_sidecars_and_survives_controller_death(self):
        from app.orphan_cleanup import CONSENT_KEY,CONSENT_VERSION,STATE_KEY
        from app.json_orphan_quarantine import review_pending_quarantine,reconcile_pending_quarantine,LEAF
        for library,req in self.requests.items():
            folder=Path(req.source_root)/req.title
            (folder/'video.mkv').unlink() # Disposable fixture setup only.
            (folder/'.DS_Store').write_bytes(b'SYNTHETIC SIDECAR ONLY')
            for stage in ('keep','removal'):(self.media_root/(library+'_'+stage)).mkdir()
        self.server.rows={}
        handler=self.server.RequestHandlerClass
        original_get=handler.do_GET
        def get(handler):
            path=urlsplit(handler.path).path
            if path=='/Users':return handler.respond([{'Id':'fixture-user'}])
            if path.endswith('/Items'):return handler.respond({'Items':[],'TotalRecordCount':0,'StartIndex':0})
            if path in ('/api/v3/movie','/api/v3/series'):return handler.respond([])
            return original_get(handler)
        handler.do_GET=get
        remote='http://127.0.0.1:'+str(self.server.server_port)
        config=self.state_root/'orphan-config.json'
        config.write_text(json.dumps({'ORPHAN_CLEANUP_ENABLED':'true',CONSENT_KEY:CONSENT_VERSION}))
        values=dict(MEDIA_PATH=str(self.media_root),STATE_FILE=str(self.store.path),WEB_CONFIG_FILE=str(config),
            DRY_RUN='false',ENABLE_MOVIES='true',ENABLE_TV='true',MAX_ACTIONS_PER_RUN='10',
            AUDITOR_STATE_BACKEND='json',AUDITOR_WORKER_MODE='json_serialized',
            JELLYFIN_HOST_URL=remote,JELLYFIN_API_TOKEN='synthetic-fixture-token',
            RADARR_URL=remote,RADARR_API_KEY='synthetic-fixture-token',SONARR_URL=remote,SONARR_API_KEY='synthetic-fixture-token',TZ='UTC')
        code="""
import json,os,signal
from datetime import datetime,timedelta,timezone
from app.json_worker_service import settings_snapshot
from app.json_worker_cycle import run_cycle
from app.json_tracking_store import JsonTrackingStore
import app.json_orphan_quarantine as module
now=datetime(2026,1,20,12,tzinfo=timezone.utc)
store=JsonTrackingStore(os.environ['STATE_FILE'])
first=run_cycle(store,settings=settings_snapshot(),trigger='manual',now=now)
assert first['result']=='completed' and not first['completed_quarantines'],first.get('failure_stage')
rename=module.rename_directory_noreplace_at
def killed(source,name,destination,target):
    rename(source,name,destination,target)
    if name=='Movie':os.kill(os.getpid(),signal.SIGKILL)
module.rename_directory_noreplace_at=killed
run_cycle(store,settings=settings_snapshot(),trigger='manual',now=now+timedelta(hours=25))
raise AssertionError('Expected fixture kill after metadata rename')
"""
        env={**os.environ,**values}
        if os.environ.get('JSON_FIXTURE_PACKAGED_APP')=='true':env['PYTHONPATH']='/app/app:/app'
        child=subprocess.run([sys.executable,'-B','-c',code],env=env,timeout=60,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertEqual(child.returncode,-9,child.stderr.decode()+child.stdout.decode())
        state=json.loads(self.store.path.read_bytes())
        self.assertEqual(state[KEY]['journal']['kind'],'orphan_quarantine')
        self.assertFalse((Path(self.requests['Movies'].source_root)/'Movie').exists())
        review=review_pending_quarantine(self.store,settings=values)
        self.assertEqual(review['required_action'],'record_quarantine')
        reconcile_pending_quarantine(self.store,settings=values,expected_fingerprint=review['review_fingerprint'])
        current=json.loads(self.store.path.read_bytes())
        self.assertIsNone(current[KEY]['journal'])
        self.assertNotIn('Movie',current['first_seen'])
        self.assertIn('TV/Show',current['first_seen'])
        receipt=next(iter(current[STATE_KEY]['quarantined'].values()))
        archive=self.media_root/LEAF/receipt['archive']
        self.assertEqual((archive/'.DS_Store').read_bytes(),b'SYNTHETIC SIDECAR ONLY')
        self.assertEqual(receipt['clocks'],{'first_seen':'2026-01-01T01:02:03'})
        self.assertFalse(any(method!='GET' for method,_ in self.server.calls))

    def deletion_case(self):
        from app.json_delete_execution import DeleteRequest
        requests={}
        for lib,old in self.requests.items():
            roots={'Waiting':old.source_root,'Holding':old.destination_root}
            for stage in ('Keep','Removal'):
                path=self.media_root/(lib+'_'+stage.lower());path.mkdir();roots[stage]=str(path)
            source=Path(old.source_root)/old.title;source.rename(Path(roots['Removal'])/old.title)
            req=DeleteRequest(lib,old.title,(NOW-timedelta(days=10)).isoformat(),7,roots,old.service,
                old.title_id,roots['Removal']+'/'+old.title,'http://127.0.0.1:'+str(self.server.server_port))
            requests[lib]=req
            row=self.server.rows['/api/v3/'+('movie' if lib=='Movies' else 'series')+'/'+str(req.title_id)]
            row.update(path=req.arr_source_path,monitored=False)
        with self.store.session() as session:
            session.state['first_seen']={}
            session.state['in_removal']={('TV/' if req.library=='TV' else '')+req.title:req.source_since for req in requests.values()}
            session.checkpoint()
        return requests

    def deletion_client(self,req,verify=lambda:None):
        from app.arr_delete_transport import ArrTitleDelete
        return ArrTitleDelete(service=req.service,base_url=req.arr_base_url,
            token='synthetic-fixture-token',source_path=req.arr_source_path,title_folder=req.title,verify_binding=verify)

    def test_movie_and_tv_arr_deletion_and_lost_ack_recovery(self):
        from app.json_delete_execution import execute_delete,review_pending_delete,acknowledge_pending_delete
        requests=self.deletion_case()
        self.server.lost_ack=True
        req=requests['TV'];client=self.deletion_client(req)
        with self.assertRaises(RuntimeError):
            with scan_attempt(self.store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
                execute_delete(attempt,request=req,now=NOW,fetch_protection=lambda _:dict(SIGNALS),
                    read_record=lambda _:client.read(req.title_id),send_delete=lambda _:client.delete(req.title_id),
                    read_absence=lambda _:client.read_absence(req.title_id),authorize=lambda:None)
        self.assertEqual(json.loads(self.store.path.read_bytes())[KEY]['journal']['kind'],'arr_delete')
        absent=lambda req:self.deletion_client(req).read_absence(req.title_id)
        review=review_pending_delete(self.store,read_absence=absent)
        acknowledge_pending_delete(self.store,read_absence=absent,expected_fingerprint=review['review_fingerprint'])
        self.server.lost_ack=False
        req=requests['Movies'];client=self.deletion_client(req)
        with scan_attempt(self.store,now=(NOW+timedelta(hours=2)).replace(tzinfo=timezone.utc),trigger='manual') as attempt:
            execute_delete(attempt,request=req,now=NOW+timedelta(hours=2),fetch_protection=lambda _:dict(SIGNALS),
                read_record=lambda _:client.read(req.title_id),send_delete=lambda _:client.delete(req.title_id),
                read_absence=lambda _:client.read_absence(req.title_id),authorize=lambda:None)
            attempt.finish(result='completed')
        current=json.loads(self.store.path.read_bytes())
        self.assertEqual(current['in_removal'],{})
        self.assertEqual(current['fixture_extension'],{'retained':'synthetic-only'})
        self.assertEqual(sum(method=='DELETE' for method,_ in self.server.calls),2)

    def test_sigkill_after_arr_delete_never_replays_delete(self):
        from app.json_delete_execution import review_pending_delete,acknowledge_pending_delete
        req=self.deletion_case()['TV']
        code="""
import os,signal,json,sys
from datetime import datetime,timezone
from app.json_delete_execution import execute_delete,DeleteRequest
from app.arr_delete_transport import ArrTitleDelete
from app.json_tracking_store import JsonTrackingStore
from app.json_scan_control import scan_attempt
req=DeleteRequest(**json.loads(sys.argv[2]))
client=ArrTitleDelete(service=req.service,base_url=req.arr_base_url,token='synthetic-fixture-token',source_path=req.arr_source_path,title_folder=req.title)
def send(_):
    client.delete(req.title_id)
    os.kill(os.getpid(),signal.SIGKILL)
with scan_attempt(JsonTrackingStore(sys.argv[1]),now=datetime(2026,1,20,12,tzinfo=timezone.utc),trigger='manual') as attempt:
    execute_delete(attempt,request=req,now=datetime(2026,1,20,12),
        fetch_protection=lambda _:dict(played=True,favorite=False,disliked=True,keep=False,keep_all=False,protected=False),
        read_record=lambda _:client.read(req.title_id),send_delete=send,
        read_absence=lambda _:client.read_absence(req.title_id),authorize=lambda:None)
"""
        env=dict(os.environ)
        if os.environ.get('JSON_FIXTURE_PACKAGED_APP')=='true': env['PYTHONPATH']='/app/app:/app'
        child=subprocess.run([sys.executable,'-B','-c',code,str(self.store.path),json.dumps(asdict(req))],
            env=env,timeout=20,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertEqual(child.returncode,-9,child.stderr.decode())
        before=json.loads(self.store.path.read_bytes())
        self.assertEqual(before[KEY]['journal']['kind'],'arr_delete')
        with self.assertRaises(RuntimeError):
            with scan_attempt(self.store,now=(NOW+timedelta(hours=2)).replace(tzinfo=timezone.utc),trigger='manual'):pass
        absent=lambda req:self.deletion_client(req).read_absence(req.title_id)
        review=review_pending_delete(self.store,read_absence=absent)
        acknowledge_pending_delete(self.store,read_absence=absent,expected_fingerprint=review['review_fingerprint'])
        self.assertEqual(sum(method=='DELETE' for method,_ in self.server.calls),1)
        self.assertNotIn('TV/Show',json.loads(self.store.path.read_bytes())['in_removal'])
        self.assertEqual(json.loads(self.store.path.read_bytes())[KEY]['last_started_at'],before[KEY]['last_started_at'])

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
        'external_requests_sent':False,'production_deletion_performed':False,'disposable_deletion_verified':True,
        'sigkill_delete_recovery_verified':True,'orphan_quarantine_and_sigkill_verified':True,
        'lost_ack_get_only_recovery_verified':True,'sigkill_move_recovery_verified':True,'actual_json_service_verified':True,'backup_recovery_boot_verified':True,'archived_clock_recovery_verified':True,'five_moves_per_library_verified':True,'packaged_entrypoint_verified':os.environ.get('JSON_FIXTURE_PACKAGED_APP') == 'true','movie_and_tv_moves_verified':True}))
    return 0


if __name__ == '__main__': raise SystemExit(main())
