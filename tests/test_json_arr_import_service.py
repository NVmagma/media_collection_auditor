"""Existing-media registration uses JSON only and never retries a lost POST."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
from urllib.parse import urlsplit

import pytest
from app import arr_import_service as imports
from app.arr_import_transport import ArrImportError
from app.json_scan_control import KEY,initialize_control,admission_status
from app.json_tracking_store import JsonTrackingStore

NOW=datetime(2026,1,20,12,tzinfo=timezone.utc)


@pytest.fixture(params=[('Movies','Waiting',None),('TV','Holding','/arr/holding')])
def case(tmp_path,monkeypatch,request):
    library,stage,alias=request.param; prefix='SONARR' if library=='TV' else 'RADARR'
    resource='series' if library=='TV' else 'movie'; provider='tvdbId' if library=='TV' else 'tmdbId'
    monkeypatch.setenv('AUDITOR_WORKER_MODE','json_serialized'); monkeypatch.setenv('AUDITOR_STATE_BACKEND','json')
    values={'AUDITOR_STATE_BACKEND':'json','DRY_RUN':'false','MAX_ACTIONS_PER_RUN':'10',
            'ENABLE_MOVIES':'true','ENABLE_TV':'true','STATE_FILE':str(tmp_path/'state.json')}
    roots={}
    for name,field,suffix in (('Waiting','TRANSIENT',''),('Holding','HOLDING','_hold'),('Keep','KEEP','_keep'),('Removal','REMOVAL','_removal')):
        path=tmp_path/(library+suffix); path.mkdir(); roots[name]=path
        values[prefix+'_'+field+'_PATH']=str(path)
    if alias: values[prefix+'_APP_'+stage.upper()+'_PATH']=alias
    folder=roots[stage]/'Import existing'; folder.mkdir(); media=folder/'video.mkv'; media.write_bytes(b'DISPOSABLE EXISTING MEDIA')
    state={key:{} for key in ('first_seen','queued','keep_seen','in_removal','arr_sync_pending')}
    key=('TV/' if library=='TV' else '')+folder.name
    state['first_seen' if stage=='Waiting' else 'queued'][key]='2026-01-01T01:02:03'
    state['extension']={'retain':['synthetic-extension',42]}
    store=JsonTrackingStore(values['STATE_FILE']); store.path.write_text(json.dumps(state))
    with store.session() as session: initialize_control(session,previous_started_at=NOW-timedelta(minutes=30))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def respond(self,row,status=200):
            self.send_response(status); self.end_headers(); self.wfile.write(json.dumps(row).encode())
        def do_GET(self):
            self.server.calls.append(('GET',self.path)); path=urlsplit(self.path).path.rsplit('/',1)[-1]
            if path=='status': return self.respond({'version':'4.0.20.3014' if library=='TV' else '6.4.4.10685'})
            if path=='qualityprofile': return self.respond([self.server.profile])
            if path=='rootfolder': return self.respond([{'path':alias or str(roots[stage]),'accessible':True}])
            if path=='lookup': return self.respond([dict(title='Import existing',titleSlug='import-existing',year=2020,
                **{provider:100},seasons=[{'seasonNumber':1,'monitored':True}])])
            if path==resource: return self.respond(self.server.records)
            if path=='77':
                row=deepcopy(self.server.records[0])
                if self.server.mode=='wrong_readback': row['monitored']=True
                return self.respond(row)
            return self.respond({},404)
        def do_POST(self):
            self.server.calls.append(('POST',self.path))
            row=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.server.payloads.append(row); self.server.records.append(dict(row,id=77))
            if self.server.mode=='lost_ack':
                self.connection.shutdown(socket.SHUT_RDWR); self.connection.close(); return
            return self.respond(self.server.records[0],201)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.calls=[]; server.records=[]; server.payloads=[]; server.mode='normal'
    server.profile={'id':2,'name':'Existing HD','cutoff':1}
    values[prefix+'_URL']='http://127.0.0.1:'+str(server.server_port); values[prefix+'_API_KEY']='synthetic-private-token'
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try: yield dict(store=store,values=values,server=server,media=media,folder=folder,
                    selection=dict(library=library,folder=folder.name,provider_id=100,quality_profile_id=2))
    finally: server.shutdown(); server.server_close(); thread.join()


def review(case): return imports.review(selection=case['selection'],settings=case['values'])
def apply(case,report): return imports.apply(selection=case['selection'],settings=case['values'],expected_fingerprint=report['review_fingerprint'])


def test_options_lookup_review_and_registration_preserve_all_tracking_and_budget(case):
    store,server=case['store'],case['server']; before=json.loads(store.path.read_bytes()); raw=store.path.read_bytes()
    media_before=(case['media'].read_bytes(),case['media'].stat().st_mtime_ns)
    options=imports.options(library=case['selection']['library'],settings=case['values'])
    assert case['folder'].name in options['folders'] and options['monitoring']=='off'
    assert imports.lookup(library=case['selection']['library'],term='existing',settings=case['values'])['matches'][0]['provider_id']==100
    report=review(case); assert store.path.read_bytes()==raw and not server.payloads
    result=apply(case,report)
    assert result['status']=='existing_media_import_verified' and result['tracking_clocks_preserved']
    assert json.loads(store.path.read_bytes())==before
    assert media_before==(case['media'].read_bytes(),case['media'].stat().st_mtime_ns)
    assert len(server.payloads)==1 and server.payloads[0]['monitored'] is False
    assert server.payloads[0]['addOptions']['monitor']=='none'
    assert all(value is False for key,value in server.payloads[0]['addOptions'].items() if key!='monitor')
    if case['selection']['library']=='TV':
        assert server.payloads[0]['monitorNewItems']=='none'
        assert all(row['monitored'] is False for row in server.payloads[0]['seasons'])
    assert 'synthetic-private-token' not in json.dumps(result)


def test_lost_create_reply_requires_get_only_recovery_and_never_reposts(case):
    report=review(case); case['server'].mode='lost_ack'
    before=json.loads(case['store'].path.read_bytes())
    with pytest.raises(ArrImportError): apply(case,report)
    pending=json.loads(case['store'].path.read_bytes()); assert pending[KEY]['journal']['kind']=='arr_import'
    assert admission_status(pending,now=NOW+timedelta(hours=3))['status']=='review_required'
    with pytest.raises(ArrImportError): apply(case,report)
    verified=imports.recover(settings=case['values']); raw=case['store'].path.read_bytes()
    assert verified['status']=='import_outcome_matches' and case['store'].path.read_bytes()==raw
    result=imports.recover(settings=case['values'],expected_fingerprint=verified['review_fingerprint'])
    assert result['arr_create_requests_sent']==0 and len(case['server'].payloads)==1
    assert json.loads(case['store'].path.read_bytes())==before


@pytest.mark.parametrize('change',['media','profile','settings','state'])
def test_changed_review_never_sends_create(case,change):
    report=review(case)
    if change=='media': case['media'].write_bytes(b'changed media')
    elif change=='profile': case['server'].profile['cutoff']=99
    elif change=='settings': case['values']['HOLDING_DAYS']='12'
    else:
        with case['store'].session() as session: session.state['extension']['changed']=True; session.checkpoint()
    with pytest.raises((RuntimeError,ValueError)): apply(case,report)
    assert not case['server'].payloads


def test_wrong_remote_monitoring_never_clears_import_intent(case):
    report=review(case); case['server'].mode='wrong_readback'
    with pytest.raises(ArrImportError): apply(case,report)
    before=case['store'].path.read_bytes()
    with pytest.raises(ArrImportError): imports.recover(settings=case['values'])
    assert case['store'].path.read_bytes()==before and len(case['server'].payloads)==1


def test_preview_refuses_create_before_intent(case):
    case['values']['DRY_RUN']='true'; report=review(case); before=case['store'].path.read_bytes()
    with pytest.raises(ArrImportError): apply(case,report)
    assert case['store'].path.read_bytes()==before and not case['server'].payloads


def test_pending_operation_refuses_review_before_any_remote_request(case):
    store=case['store']
    with store.session() as session:
        session.state[KEY]['journal']=dict(id='a'*32,kind='move',phase='intent_recorded',
            library=case['selection']['library'],title=case['selection']['folder'],details={'synthetic':True})
        session.checkpoint()
    before=store.path.read_bytes()
    with pytest.raises(ArrImportError): review(case)
    assert store.path.read_bytes()==before and not case['server'].calls


def test_worker_lock_blocks_import_before_get_or_post(case):
    from concurrent.futures import ThreadPoolExecutor
    from app.state_lock import StateLockBusy
    with case['store'].session():
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(review,case)
            with pytest.raises(StateLockBusy): future.result(timeout=5)
    assert not case['server'].calls
