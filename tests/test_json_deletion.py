"""Actual disposable files plus loopback Arr deletion; never production services."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json,os,shutil,socket,threading
from urllib.parse import urlsplit,parse_qs
import pytest

from app.arr_delete_transport import ArrTitleDelete
from app.deletion_policy import CONSENT_KEY,CONSENT_VERSION
from app.json_delete_execution import DeleteRequest,execute_delete,review_pending_delete,acknowledge_pending_delete
from app.json_scan_control import KEY,scan_attempt,initialize_control,ScanAdmissionBlocked
from app.json_tracking_store import JsonTrackingStore
from app.json_worker_cycle import validate_policy
from app.json_lifecycle_plan import LibraryObservation,TitleObservation,plan_scan
from test_json_move_execution import NOW,SIG


@pytest.fixture
def deletion(tmp_path):
    state={key:{} for key in ('first_seen','queued','in_removal','keep_seen','arr_sync_pending')}
    state['unknown']={'retain':'extension'}
    store=JsonTrackingStore(tmp_path/'state.json')
    roots={}; reqs={}
    for library,title,id_ in (('Movies','Example (2000)',1),('TV','Example Show',2)):
        mapping={}
        for stage in ('Waiting','Holding','Keep','Removal'):
            root=tmp_path/(library+'_'+stage);root.mkdir();mapping[stage]=str(root)
        folder=Path(mapping['Removal'])/title;folder.mkdir()
        (folder/'video.mkv').write_bytes(b'disposable media')
        stamp=(NOW-timedelta(days=20)).timestamp();os.utime(folder/'video.mkv',(stamp,stamp))
        since=(NOW-timedelta(days=10)).isoformat(); key=('TV/' if library=='TV' else '')+title
        state['in_removal'][key]=since;roots[library]=mapping
        reqs[library]=DeleteRequest(library,title,since,7,mapping,'radarr' if library=='Movies' else 'sonarr',id_,str(folder),'http://127.0.0.1:1')
    store.path.write_text(json.dumps(state))
    with store.session() as session:initialize_control(session,previous_started_at=(NOW-timedelta(hours=2)).replace(tzinfo=timezone.utc))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            self.server.calls.append(('GET',self.path))
            if self.server.mode=='unauthorized':self.send_response(401);self.end_headers();return
            path=urlsplit(self.path).path
            if path in ('/api/v3/movie','/api/v3/series'):
                record=[row for key,row in self.server.records.items() if key.startswith(path+'/')]
            else: record=self.server.records.get(path)
            self.send_response(200 if record else 404);self.end_headers()
            self.wfile.write(json.dumps(record).encode())
        def do_DELETE(self):
            self.server.calls.append(('DELETE',self.path))
            assert self.headers['X-Api-Key']=='synthetic-token'
            query=parse_qs(urlsplit(self.path).query)
            assert query['deleteFiles']==['true']
            record=self.server.records.pop(urlsplit(self.path).path)
            if self.server.mode=='async':
                from time import sleep
                def remove_later():
                    sleep(0.3);shutil.rmtree(record['path'])
                threading.Thread(target=remove_later,daemon=True).start()
            else: shutil.rmtree(record['path']) # Test server simulates Arr, only tmp_path.
            if self.server.mode=='lost_ack':
                self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            self.send_response(200);self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.calls=[];server.mode='normal';server.records={}
    for req in reqs.values():
        server.records['/api/v3/'+('movie' if req.library=='Movies' else 'series')+'/'+str(req.title_id)]={
            'id':req.title_id,'path':req.arr_source_path,'monitored':False}
    reqs={key:replace(req,arr_base_url='http://127.0.0.1:'+str(server.server_port)) for key,req in reqs.items()}
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield store,reqs,server
    finally:server.shutdown();server.server_close();thread.join()


def client(req,server,verify=lambda:None):
    return ArrTitleDelete(service=req.service,base_url='http://127.0.0.1:'+str(server.server_port),
        token='synthetic-token',source_path=req.arr_source_path,title_folder=req.title,verify_binding=verify)


def execute(attempt,req,server,**kw):
    transport=client(req,server,attempt.session.verify)
    args=dict(request=req,now=NOW,fetch_protection=lambda _:dict(SIG),read_record=lambda _:transport.read(req.title_id),
        send_delete=lambda _:transport.delete(req.title_id),read_absence=lambda _:transport.read_absence(req.title_id),authorize=lambda:None)
    args.update(kw)
    return execute_delete(attempt,**args)


def test_movie_and_tv_actual_delete_have_exact_exclusions_and_preserve_other_clocks(deletion):
    store,reqs,server=deletion
    with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
        for req in reqs.values():execute(attempt,req,server)
        attempt.finish(result='completed')
    current=json.loads(store.path.read_bytes())
    assert current['in_removal']=={} and current['unknown']=={'retain':'extension'}
    assert current[KEY]['journal'] is None
    deletes=[path for method,path in server.calls if method=='DELETE']
    assert len(deletes)==2 and 'addImportExclusion=true' in deletes[0] and 'addImportListExclusion=true' in deletes[1]
    for req in reqs.values():assert not Path(req.arr_source_path).exists()
    assert 'synthetic-token' not in store.path.read_text()


@pytest.mark.parametrize('protection',[None,*[{**SIG,k:True} for k in ('favorite','keep','keep_all','protected')]])
def test_unknown_or_protected_title_never_dispatches(deletion,protection):
    store,reqs,server=deletion
    with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
        with pytest.raises(RuntimeError):execute(attempt,reqs['Movies'],server,fetch_protection=lambda _:protection)
        assert attempt.session.state[KEY]['journal'] is None
    assert not any(m=='DELETE' for m,_ in server.calls)


@pytest.mark.parametrize('change',['recent','future_clock','wrong_stage','monitored','symlink','hardlink','duplicate_stage','new_content','revoked'])
def test_preflight_blocks_before_intent_or_delete(deletion,change,tmp_path):
    store,reqs,server=deletion;req=reqs['Movies'];folder=Path(req.arr_source_path)
    with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
        kwargs={}
        if change in ('recent','future_clock'):
            since=(NOW+timedelta(days=1) if change=='future_clock' else NOW-timedelta(days=1)).isoformat()
            req=replace(req,source_since=since);attempt.session.state['in_removal'][req.title]=since;attempt.session.checkpoint()
        if change=='wrong_stage':
            attempt.session.state['queued'][req.title]=attempt.session.state['in_removal'].pop(req.title);attempt.session.checkpoint()
        if change=='monitored':server.records['/api/v3/movie/1']['monitored']=True
        if change=='symlink':(folder/'sidecar').symlink_to(tmp_path/'outside')
        if change=='hardlink':os.link(folder/'video.mkv',tmp_path/'outside.mkv')
        if change=='duplicate_stage':(Path(req.roots['Keep'])/req.title).mkdir()
        if change=='new_content':os.utime(folder/'video.mkv',(NOW.timestamp(),NOW.timestamp()))
        if change=='revoked':
            def refuse():raise RuntimeError('Revoked')
            kwargs['authorize']=refuse
        with pytest.raises((RuntimeError,ValueError)):execute(attempt,req,server,**kwargs)
        assert attempt.session.state[KEY]['journal'] is None
    assert not any(m=='DELETE' for m,_ in server.calls) and folder.exists()


def test_new_favorite_after_intent_blocks_and_cannot_auto_replay(deletion):
    store,reqs,server=deletion;seen=[]
    def protection(_):seen.append(1);return {**SIG,'favorite':len(seen)>1}
    with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
        with pytest.raises(RuntimeError):execute(attempt,reqs['Movies'],server,fetch_protection=protection)
        assert attempt.session.state[KEY]['journal']['kind']=='arr_delete'
    with pytest.raises(ScanAdmissionBlocked):
        with scan_attempt(store,now=(NOW+timedelta(hours=2)).replace(tzinfo=timezone.utc),trigger='manual'):pass
    assert not any(m=='DELETE' for m,_ in server.calls)


def test_lost_ack_requires_fresh_get_only_review_and_no_delete_replay(deletion):
    store,reqs,server=deletion;server.mode='lost_ack';req=reqs['TV']
    with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
        with pytest.raises(RuntimeError):execute(attempt,req,server)
    before=store.path.read_bytes()
    absent=lambda req:client(req,server).read_absence(req.title_id)
    review=review_pending_delete(store,read_absence=absent)
    assert store.path.read_bytes()==before
    with pytest.raises(RuntimeError):acknowledge_pending_delete(store,read_absence=absent,expected_fingerprint='0'*64)
    acknowledge_pending_delete(store,read_absence=absent,expected_fingerprint=review['review_fingerprint'])
    current=json.loads(store.path.read_bytes())
    assert current[KEY]['journal'] is None and list(current['in_removal'])==[reqs['Movies'].title]
    assert sum(m=='DELETE' for m,_ in server.calls)==1
    with pytest.raises(RuntimeError):acknowledge_pending_delete(store,read_absence=absent,expected_fingerprint=review['review_fingerprint'])


def test_timeout_or_unauthorized_cannot_prove_absence(deletion):
    store,reqs,server=deletion;server.mode='unauthorized'
    with pytest.raises(RuntimeError):client(reqs['TV'],server).read_absence(2)


def test_planner_retains_one_deletion_per_library_and_shared_action_cap(deletion):
    store,reqs,_=deletion;state=json.loads(store.path.read_bytes());libs=[]
    for lib,req in reqs.items():
        key=('TV/' if lib=='TV' else '')+req.title
        state['in_removal'][key+' 2']=req.source_since
        libs.append(LibraryObservation(lib,True,True,tuple(TitleObservation(k,'Removal',7,dict(SIG),'exact_source_match') for k in (key,key+' 2'))))
    off=plan_scan(snapshot=state,libraries=libs,now=NOW,per_library_action_limit=5)
    assert not off['deletions']
    result=plan_scan(snapshot=state,libraries=libs,now=NOW,per_library_action_limit=5,deletion_enabled=True)
    assert len(result['deletions'])==2 and len([r for r in result['decisions'] if r.outcome=='capped'])==2
    assert not result['moves'] and not result['permanent_deletion_authorized']


def test_consent_is_explicit_and_unsupported_destructive_options_remain_off():
    values={'ALLOW_PERMANENT_DELETE':'true'}
    with pytest.raises(ValueError):validate_policy(values)
    values[CONSENT_KEY]=CONSENT_VERSION
    assert validate_policy(values)[0]['ALLOW_PERMANENT_DELETE']=='true'
    for name in ('ENABLE_SEASON_PRUNING','ALLOW_FILESYSTEM_DELETE','ALLOW_CROSS_FILESYSTEM_MOVES'):
        with pytest.raises(ValueError):validate_policy({**values,name:'true'})
    with pytest.raises(ValueError):validate_policy({**values,'REMOVAL_DAYS':'0'})


def test_unchanged_unperformed_deletion_can_be_canceled_without_replay(deletion):
    store,reqs,server=deletion;req=reqs['Movies'];seen=[]
    def protection(_):seen.append(1);return {**SIG,'favorite':len(seen)>1}
    with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
        with pytest.raises(RuntimeError):execute(attempt,req,server,fetch_protection=protection)
    read=lambda req:client(req,server).read(req.title_id)
    absent=lambda req:client(req,server).read_absence(req.title_id)
    review=review_pending_delete(store,read_absence=absent,read_record=read)
    assert review['required_action']=='cancel_unperformed_delete'
    acknowledge_pending_delete(store,read_absence=absent,read_record=read,
        expected_fingerprint=review['review_fingerprint'],expected_outcome='unchanged')
    assert json.loads(store.path.read_bytes())['in_removal'][req.title]==req.source_since
    assert json.loads(store.path.read_bytes())[KEY]['journal'] is None
    assert not any(m=='DELETE' for m,_ in server.calls)


def test_content_change_after_review_never_clears_intent(deletion):
    store,reqs,server=deletion;req=reqs['Movies']
    calls=[]
    def protect(_):
        calls.append(1); return {**SIG,'favorite':len(calls)>1}
    with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
        with pytest.raises(RuntimeError):execute(attempt,req,server,fetch_protection=protect)
    read=lambda req:client(req,server).read(req.title_id)
    absent=lambda req:client(req,server).read_absence(req.title_id)
    review=review_pending_delete(store,read_absence=absent,read_record=read)
    (Path(req.arr_source_path)/'video.mkv').write_bytes(b'new media')
    before=store.path.read_bytes()
    with pytest.raises(RuntimeError):acknowledge_pending_delete(store,read_absence=absent,read_record=read,
        expected_fingerprint=review['review_fingerprint'],expected_outcome='unchanged')
    assert store.path.read_bytes()==before


def test_full_cycle_preview_and_live_remove_only_expired_unprotected_titles(deletion,monkeypatch):
    from app.json_worker_cycle import run_cycle,JSONMoveServices
    from app.json_readonly_scan import collect_worker_scan,rehearse_scan
    store,reqs,server=deletion
    values={'DRY_RUN':'true','ALLOW_PERMANENT_DELETE':'true',CONSENT_KEY:CONSENT_VERSION,
        'ENABLE_MOVIES':'true','ENABLE_TV':'true','MAX_ACTIONS_PER_RUN':'10','TZ':'UTC','REMOVAL_DAYS':'7'}
    for req in reqs.values():
        prefix='SONARR' if req.library=='TV' else 'RADARR'
        values[prefix+'_URL']=req.arr_base_url;values[prefix+'_API_KEY']='synthetic-token'
        for stage,field in (('Waiting','TRANSIENT'),('Holding','HOLDING'),('Keep','KEEP'),('Removal','REMOVAL')):
            values[prefix+'_'+field+'_PATH']=req.roots[stage]
    def collect(**kw):
        libs=[]
        for inventory in kw['inventories']:
            titles=tuple(TitleObservation(('TV/' if inventory.library=='TV' else '')+r.folder,r.stage,r.threshold_days,dict(SIG),'exact_source_match',r.blocker) for r in inventory.titles)
            libs.append(LibraryObservation(inventory.library,True,True,titles))
        return plan_scan(snapshot=kw['snapshot'],libraries=libs,now=kw['now'],per_library_action_limit=5,deletion_enabled=True)
    before=store.path.read_bytes()
    preview=run_cycle(store,settings=values,trigger='manual',now=NOW.replace(tzinfo=timezone.utc),
        preview=lambda **kw:rehearse_scan(collect=collect,**kw))
    assert len(preview['deletions'])==2 and not server.calls and store.path.read_bytes()==before
    values['DRY_RUN']='false'
    class Services(JSONMoveServices):
        def protection(self,req,now):return dict(SIG)
    monkeypatch.setattr('app.json_worker_service.settings_snapshot',lambda:dict(values))
    result=run_cycle(store,settings=values,trigger='manual',now=NOW.replace(tzinfo=timezone.utc),
        services=Services(values),collect=lambda session,**kw:collect_worker_scan(session,collect=collect,**kw))
    assert result['result']=='completed' and len(result['completed_deletions'])==2
    assert not result['completed_moves'] and not result['pending_operation_present']
    assert json.loads(store.path.read_bytes())['in_removal']=={}


def test_current_settings_revocation_blocks_destructive_adapter(deletion,monkeypatch):
    from app.json_worker_cycle import JSONMoveServices
    values={'DRY_RUN':'false','ALLOW_PERMANENT_DELETE':'true',CONSENT_KEY:CONSENT_VERSION}
    service=JSONMoveServices(values)
    monkeypatch.setattr('app.json_worker_service.settings_snapshot',lambda:{**values,'ALLOW_PERMANENT_DELETE':'false'})
    with pytest.raises(RuntimeError):service.authorize_delete()


def test_dispatched_but_still_present_is_not_proof_of_unperformed_delete(deletion):
    store,reqs,server=deletion;req=reqs['Movies']
    def unknown(_):raise RuntimeError('Response lost before outcome known')
    with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
        with pytest.raises(RuntimeError):execute(attempt,req,server,send_delete=unknown)
    before=store.path.read_bytes()
    with pytest.raises(RuntimeError):review_pending_delete(store,
        read_absence=lambda req:client(req,server).read_absence(req.title_id),
        read_record=lambda req:client(req,server).read(req.title_id))
    assert store.path.read_bytes()==before


def test_async_arr_file_removal_is_observed_without_resending_delete(deletion):
    store,reqs,server=deletion;server.mode='async';req=reqs['Movies']
    with scan_attempt(store,now=NOW.replace(tzinfo=timezone.utc),trigger='manual') as attempt:
        execute(attempt,req,server)
        attempt.finish(result='completed')
    assert not Path(req.arr_source_path).exists()
    assert sum(m=='DELETE' for m,_ in server.calls)==1
    assert json.loads(store.path.read_bytes())[KEY]['journal'] is None
