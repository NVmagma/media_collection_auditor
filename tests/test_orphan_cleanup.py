"""Disposable Movie/TV leftovers, real bounded GETs and no permanent deletion."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json,os,struct,threading
from urllib.parse import urlsplit,parse_qs
import pytest

from app.orphan_inventory import inspect_title
from app.orphan_cleanup import STATE_KEY,CONSENT_KEY,CONSENT_VERSION,control,plan_cleanup,record_observations
from app.json_tracking_store import JsonTrackingStore
from app.json_scan_control import KEY,initialize_control,scan_attempt,ScanAdmissionBlocked
from app.json_worker_cycle import JSONMoveServices,run_cycle
from app.json_readonly_scan import collect_worker_scan,rehearse_scan
from app.json_orphan_quarantine import execute_quarantine,review_pending_quarantine,reconcile_pending_quarantine,LEAF

NOW=datetime(2026,1,20,12,tzinfo=timezone.utc)


@pytest.fixture
def orphan(tmp_path,monkeypatch):
    media=tmp_path/'media';media.mkdir(); roots={};folders={}
    values={'MEDIA_PATH':str(media),'ENABLE_MOVIES':'true','ENABLE_TV':'true','DRY_RUN':'false',
        'ORPHAN_CLEANUP_ENABLED':'true',CONSENT_KEY:CONSENT_VERSION,'TZ':'UTC','MAX_ACTIONS_PER_RUN':'10'}
    state={key:{} for key in ('first_seen','queued','in_removal','keep_seen','arr_sync_pending')};state['unknown']={'retain':True}
    for library,prefix,title in (('Movies','RADARR','Gone (2000)'),('TV','SONARR','Gone Show')):
        roots[library]={}
        for stage,field in (('Waiting','TRANSIENT'),('Holding','HOLDING'),('Keep','KEEP'),('Removal','REMOVAL')):
            path=media/(library+'_'+stage);path.mkdir();roots[library][stage]=path
            values[prefix+'_'+field+'_PATH']=str(path)
        folder=roots[library]['Waiting']/title;folder.mkdir();folders[library]=folder
        (folder/'.DS_Store').write_bytes(b'synthetic metadata')
        state['first_seen'][('TV/' if library=='TV' else '')+title]='2025-12-01T01:02:03'
    store=JsonTrackingStore(tmp_path/'state.json');store.path.write_text(json.dumps(state))
    with store.session() as session:initialize_control(session,previous_started_at=NOW-timedelta(hours=2))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            self.server.calls.append(('GET',self.path));url=urlsplit(self.path)
            if self.server.mode=='unavailable':self.send_response(503);self.end_headers();return
            if url.path=='/Users':row=[{'Id':'fixture-user'}]
            elif url.path.endswith('/Items'):
                library='TV' if parse_qs(url.query).get('IncludeItemTypes')==['Series'] else 'Movies'
                rows=self.server.jellyfin[library];row={'Items':rows,'TotalRecordCount':len(rows),'StartIndex':0}
            elif url.path=='/api/v3/movie':row=self.server.catalogs['Movies']
            elif url.path=='/api/v3/series':row=self.server.catalogs['TV']
            else:self.send_response(404);self.end_headers();return
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps(row).encode())
        def do_DELETE(self):raise AssertionError('No DELETE is allowed')
        def do_PUT(self):raise AssertionError('No Arr writes allowed')
        def do_POST(self):raise AssertionError('No Arr writes allowed')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.calls=[];server.mode='normal'
    server.catalogs={'Movies':[],'TV':[]};server.jellyfin={'Movies':[],'TV':[]}
    url='http://127.0.0.1:'+str(server.server_port)
    values.update(JELLYFIN_HOST_URL=url,JELLYFIN_API_TOKEN='synthetic-token')
    for prefix in ('RADARR','SONARR'):values[prefix+'_URL']=url;values[prefix+'_API_KEY']='synthetic-token'
    monkeypatch.setattr('app.json_worker_service.settings_snapshot',lambda:deepcopy(values))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield store,values,folders,server
    finally:server.shutdown();server.server_close();thread.join()


def cycle(case,now=NOW):
    store,values,_,_=case
    return run_cycle(store,settings=values,trigger='manual',now=now,services=JSONMoveServices(values))


def test_live_observation_then_movie_tv_quarantine_preserves_metadata_clocks_and_unknowns(orphan):
    store,values,folders,server=orphan;old=json.loads(store.path.read_bytes())
    first=cycle(orphan)
    assert first['result']=='completed' and not first['completed_quarantines']
    assert all(row['reason']=='orphan_observation_wait' for row in first['decisions'])
    assert not (Path(values['MEDIA_PATH'])/LEAF).exists()
    second=cycle(orphan,NOW+timedelta(hours=25))
    assert second['result']=='completed' and len(second['completed_quarantines'])==2
    state=json.loads(store.path.read_bytes());assert state['first_seen']=={} and state['unknown']==old['unknown']
    assert state[KEY]['journal'] is None
    for receipt in state[STATE_KEY]['quarantined'].values():
        folder=receipt['folder'];archive=Path(values['MEDIA_PATH'])/LEAF/receipt['archive']
        assert (archive/'.DS_Store').read_bytes()==b'synthetic metadata'
        assert not folders[folder['library']].exists()
        assert receipt['clocks']=={'first_seen':old['first_seen'][folder['media_key']]}
        assert receipt['quarantine_path']==values['MEDIA_PATH']+'/'+LEAF
    assert all(method=='GET' for method,_ in server.calls)
    assert 'synthetic-token' not in store.path.read_text()


def test_preview_never_records_observations_or_moves_metadata(orphan):
    store,values,folders,_=orphan;before=store.path.read_bytes();values['DRY_RUN']='true'
    result=cycle(orphan)
    assert result['execution_mode']=='preview' and store.path.read_bytes()==before
    assert all(folder.exists() for folder in folders.values())
    assert all(row.reason=='orphan_observation_wait' for row in result['decisions'])


@pytest.mark.parametrize('name',['video.mkv','.hidden.mp4','video.MP4','disc.iso','index.bdmv','show.strm','clip.webm'])
def test_any_video_including_empty_hidden_and_disc_files_prevents_cleanup(orphan,name):
    _,_,folders,_=orphan;folder=folders['TV'];season=folder/'Season 1';season.mkdir();(season/name).write_bytes(b'')
    assert inspect_title(str(folder))['status']=='video_present'


@pytest.mark.parametrize('name',['unknown.bin','video.mkv.part','.hidden-lock','download.zip'])
def test_unknown_or_incomplete_files_are_preserved(orphan,name):
    _,_,folders,_=orphan;(folders['Movies']/name).write_bytes(b'unknown')
    assert inspect_title(str(folders['Movies']))['status']=='unknown_files'
    cycle(orphan);result=cycle(orphan,NOW+timedelta(hours=25))
    assert folders['Movies'].exists()
    assert not any(row['library']=='Movies' for row in result['completed_quarantines'])


def test_appledouble_mkv_is_metadata_only_when_header_is_valid_and_has_no_data_fork(orphan):
    _,_,folders,_=orphan;folder=folders['Movies'];fork=folder/'._movie.mkv'
    fork.write_bytes(struct.pack('>II16sH',0x00051607,0x00020000,b'\0'*16,0))
    assert inspect_title(str(folder))['status']=='metadata_only'
    fork.write_bytes(b'not an AppleDouble header')
    assert inspect_title(str(folder))['status']=='video_present'
    fork.write_bytes(struct.pack('>II16sHIII',0x00051607,0x00020000,b'\0'*16,1,1,38,1)+b'X')
    assert inspect_title(str(folder))['status']=='video_present'


def test_empty_and_nested_metadata_folder_is_detected(orphan):
    _,_,folders,_=orphan;folder=folders['TV'];(folder/'.DS_Store').unlink()
    assert inspect_title(str(folder))['status']=='metadata_only'
    nested=folder/'Season 1';nested.mkdir();(nested/'poster.jpg').write_bytes(b'poster')
    assert inspect_title(str(folder))['status']=='metadata_only'


@pytest.mark.parametrize('mode',['unavailable','arr_managed','jellyfin_managed'])
def test_service_failure_or_managed_title_never_becomes_cleanup_permission(orphan,mode):
    _,_,folders,server=orphan
    if mode=='unavailable':server.mode=mode
    elif mode=='arr_managed':server.catalogs['Movies']=[{'id':1,'path':str(folders['Movies']),'monitored':False}]
    else:server.jellyfin['Movies']=[{'Id':'title-id','Type':'Movie','Name':'Gone','Path':str(folders['Movies']/'video.mkv'),
        'Tags':['keep-forever'],'UserData':{'IsFavorite':True,'Played':False,'PlayCount':0}}]
    cycle(orphan);result=cycle(orphan,NOW+timedelta(hours=25))
    assert folders['Movies'].exists() and not any(row['library']=='Movies' for row in result['completed_quarantines'])


def test_video_arriving_or_metadata_changing_resets_cleanup_observation(orphan):
    store,_,folders,_=orphan;cycle(orphan)
    (folders['Movies']/'new.mkv').write_bytes(b'video arrived')
    (folders['TV']/'.DS_Store').write_bytes(b'new metadata')
    result=cycle(orphan,NOW+timedelta(hours=25))
    assert not result['completed_quarantines'] and all(folder.exists() for folder in folders.values())
    saved=json.loads(store.path.read_bytes())[STATE_KEY]['observations']
    assert 'Gone (2000)' not in saved and saved['TV/Gone Show']['first_observed_at']==(NOW+timedelta(hours=25)).isoformat()


def test_keep_folders_are_preserved(orphan):
    store,values,folders,_=orphan;source=folders['Movies'];target=Path(values['RADARR_KEEP_PATH'])/source.name
    source.rename(target)
    with store.session() as session:
        session.state['keep_seen'][source.name]=session.state['first_seen'].pop(source.name);session.checkpoint()
    cycle(orphan);result=cycle(orphan,NOW+timedelta(hours=25))
    assert target.exists() and not any(row['library']=='Movies' for row in result['completed_quarantines'])


def test_symlinks_hardlinks_and_unknown_hidden_files_do_not_qualify(orphan,tmp_path):
    _,_,folders,_=orphan;folder=folders['Movies']
    external=tmp_path/'outside';external.write_bytes(b'keep')
    link=folder/'poster.jpg';link.symlink_to(external)
    with pytest.raises(RuntimeError):inspect_title(str(folder))
    link.unlink();os.link(external,link)
    assert inspect_title(str(folder))['status']=='unknown_files'
    assert external.read_bytes()==b'keep'


def test_cleanup_disabled_still_reports_metadata_without_generic_jellyfin_error(orphan):
    _,values,folders,_=orphan;values['ORPHAN_CLEANUP_ENABLED']='false'
    result=cycle(orphan)
    assert all(row['reason']=='orphan_cleanup_disabled' for row in result['decisions'])
    assert all(folder.exists() for folder in folders.values())


def test_real_rename_interruption_retains_intent_and_explicit_recovery_never_repeats_it(orphan,monkeypatch):
    import app.json_orphan_quarantine as module
    store,values,folders,_=orphan;cycle(orphan)
    original=module.rename_directory_noreplace_at
    def interrupted(source,name,destination,target):
        original(source,name,destination,target)
        if name==folders['Movies'].name:raise RuntimeError('Interrupted after rename')
    monkeypatch.setattr(module,'rename_directory_noreplace_at',interrupted)
    result=cycle(orphan,NOW+timedelta(hours=25))
    assert result['result']=='failed' and result['pending_operation_present']
    before=store.path.read_bytes();review=review_pending_quarantine(store,settings=values)
    assert store.path.read_bytes()==before and review['required_action']=='record_quarantine'
    with pytest.raises(RuntimeError):reconcile_pending_quarantine(store,settings=values,expected_fingerprint='0'*64)
    reconcile_pending_quarantine(store,settings=values,expected_fingerprint=review['review_fingerprint'])
    current=json.loads(store.path.read_bytes())
    assert current[KEY]['journal'] is None and 'Gone (2000)' not in current['first_seen']
    assert len(current[STATE_KEY]['quarantined'])==1 and folders['TV'].exists()
    assert not folders['Movies'].exists()


def test_added_video_immediately_before_quarantine_is_never_moved(orphan):
    store,values,folders,_=orphan;cycle(orphan)
    future=NOW+timedelta(hours=25)
    with scan_attempt(store,now=future,trigger='manual') as attempt:
        plan=collect_worker_scan(attempt.session,settings=values,now=future.replace(tzinfo=None))
        planned=plan_cleanup(attempt.session.state,plan,values,future);record_observations(attempt.session,planned)
        row=planned['ready'][0]
        def changed(_):
            (folders[row['library']]/'late.mkv').write_bytes(b'new video');return True
        with pytest.raises(RuntimeError):execute_quarantine(attempt,row=row,settings=values,now=future,
            fresh_absence=changed,authorize=lambda:None)
        assert attempt.session.state[KEY]['journal'] is None
    assert (folders[row['library']]/'late.mkv').exists()


def test_video_appearing_during_rename_requires_explicit_no_overwrite_restoration(orphan,monkeypatch):
    import app.json_orphan_quarantine as module
    store,values,folders,_=orphan;cycle(orphan);original=module.rename_directory_noreplace_at
    def arrived(source,name,destination,target):
        original(source,name,destination,target)
        if name==folders['Movies'].name:
            descriptor=os.open(target,os.O_RDONLY|os.O_DIRECTORY,dir_fd=destination)
            try:
                child=os.open('late.mkv',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600,dir_fd=descriptor)
                with os.fdopen(child,'wb') as stream:stream.write(b'new video')
            finally:os.close(descriptor)
    monkeypatch.setattr(module,'rename_directory_noreplace_at',arrived)
    result=cycle(orphan,NOW+timedelta(hours=25))
    assert result['pending_operation_present'] and not folders['Movies'].exists()
    review=review_pending_quarantine(store,settings=values)
    assert review['required_action']=='restore_quarantine_source'
    with pytest.raises(RuntimeError):reconcile_pending_quarantine(store,settings=values,expected_fingerprint=review['review_fingerprint'])
    restored=reconcile_pending_quarantine(store,settings=values,expected_fingerprint=review['review_fingerprint'],restore_source=True)
    assert restored['status']=='quarantine_restored_to_source'
    assert (folders['Movies']/'late.mkv').read_bytes()==b'new video'
    assert (folders['Movies']/'.DS_Store').read_bytes()==b'synthetic metadata'
    state=json.loads(store.path.read_bytes());assert state[KEY]['journal'] is None
    assert 'Gone (2000)' in state['first_seen']


def test_computed_policy_fields_do_not_falsely_revoke_matching_consent(orphan):
    from app.json_worker_cycle import validate_policy
    _,values,_,_=orphan
    captured,_=validate_policy(values)
    adapter=JSONMoveServices(captured)
    adapter.authorize_orphan()


@pytest.mark.parametrize('name,header', [('poster.jpg',b'\x00\x00\x00\x18ftypisom'),('movie.nfo',b'\x1aE\xdf\xa3FAKE'),('.DS_Store',b'RIFF\x00\x00\x00\x00AVI ')])
def test_common_video_headers_are_preserved_even_when_named_like_metadata(orphan,name,header):
    _,_,folders,_=orphan;(folders['Movies']/name).write_bytes(header)
    assert inspect_title(str(folders['Movies']))['status']=='video_present'
