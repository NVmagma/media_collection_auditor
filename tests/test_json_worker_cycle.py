"""End-to-end JSON cycle: admission, real inventory, moves and Arr readbacks."""
from copy import deepcopy
from datetime import timedelta, timezone
import json
from pathlib import Path

import pytest
from app.json_worker_cycle import run_cycle,JSONMoveServices
from app.json_readonly_scan import collect_worker_scan,rehearse_scan
from app.json_scan_control import KEY,ScanAdmissionBlocked
from test_json_move_execution import move_case,NOW,SIG
from test_json_readonly_scan import fake_collect


@pytest.fixture
def cycle_case(move_case):
    store,roots,requests,server=move_case
    values={'DRY_RUN':'false','MAX_ACTIONS_PER_RUN':'2','ENABLE_TV':'true','TZ':'UTC'}
    for library,prefix in (('Movies','RADARR'),('TV','SONARR')):
        values[prefix+'_URL']='http://127.0.0.1:'+str(server.server_port)
        values[prefix+'_API_KEY']='synthetic-token'
        source,destination=roots[library]
        for stage,field in (('Waiting','TRANSIENT'),('Holding','HOLDING'),('Keep','KEEP'),('Removal','REMOVAL')):
            path=source if stage == 'Waiting' else destination if stage == 'Holding' else source.with_name(library+'_'+stage.lower())
            path.mkdir(exist_ok=True); values[prefix+'_'+field+'_PATH']=str(path)
    server.records['/api/v3/movie']=[deepcopy(server.records['/api/v3/movie/1'])]
    server.records['/api/v3/series']=[deepcopy(server.records['/api/v3/series/2'])]
    class Services(JSONMoveServices):
        def protection(self,request,now): return dict(SIG)
    return store,values,requests,server,Services


def collect(session,**kwargs): return collect_worker_scan(session,collect=fake_collect,**kwargs)
def preview(**kwargs): return rehearse_scan(collect=fake_collect,**kwargs)


def run(case,**kwargs):
    store,values,_,_,services=case
    return run_cycle(store,settings=values,trigger='manual',now=NOW.replace(tzinfo=timezone.utc),
        services=services(values),collect=collect,preview=preview,**kwargs)


def test_cycle_completes_movie_and_show_and_preserves_extensions(cycle_case):
    store,values,requests,server,_=cycle_case
    before=json.loads(store.path.read_bytes())
    result=run(cycle_case)
    state=json.loads(store.path.read_bytes())
    assert result['result'] == 'completed' and result['scanned_titles'] == 2
    assert len(result['decisions']) == len(result['completed_moves']) == 2
    assert not result['pending_operation_present']
    assert state[KEY]['last_result'] == 'completed' and state['unknown'] == before['unknown']
    assert state['queued'] == {'Movie':NOW.isoformat(),'TV/Show':NOW.isoformat()}
    assert sum(method == 'PUT' for method,_ in server.calls) == 2
    for req in requests.values(): assert (Path(req.destination_root)/req.title/'video.mkv').is_file()
    with pytest.raises(ScanAdmissionBlocked): run(cycle_case)
    assert sum(method == 'PUT' for method,_ in server.calls) == 2


def test_lost_tv_ack_retains_movie_completion_and_tv_journal(cycle_case):
    store,values,_,server,services=cycle_case
    class LostTV(services):
        def prepare(self,decision,session):
            if decision.library == 'TV': server.mode='lost_ack'
            return super().prepare(decision,session)
    cycle_case=store,values,cycle_case[2],server,LostTV
    result=run(cycle_case); state=json.loads(store.path.read_bytes())
    assert result['result'] == 'failed' and result['failure_stage'] == 'move_and_sync'
    assert [row['library'] for row in result['completed_moves']] == ['Movies']
    assert result['pending_operation_present'] and state[KEY]['journal']['library'] == 'TV'
    assert state['queued']['TV/Show'] == NOW.isoformat()
    with pytest.raises(ScanAdmissionBlocked):
        run_cycle(store,settings=values,trigger='manual',now=(NOW+timedelta(hours=2)).replace(tzinfo=timezone.utc))
    assert sum(method == 'PUT' for method,_ in server.calls) == 2
    assert 'synthetic-token' not in json.dumps(result)


def test_new_tv_favorite_stops_before_intent_without_losing_movie_result(cycle_case):
    store,values,requests,server,services=cycle_case
    class Favorite(services):
        def protection(self,request,now): return {**SIG,'favorite':request.library == 'TV'}
    result=run((store,values,requests,server,Favorite)); state=json.loads(store.path.read_bytes())
    assert result['result'] == 'failed' and not result['pending_operation_present']
    assert len(result['completed_moves']) == 1 and state[KEY]['last_result'] == 'failed'
    assert (Path(requests['TV'].source_root)/'Show').is_dir()
    assert sum(method == 'PUT' for method,_ in server.calls) == 1


def test_preview_is_byte_identical_and_does_not_consume_live_cooldown(cycle_case):
    store,values,_,server,_=cycle_case; values['DRY_RUN']='true'
    before=store.path.read_bytes(); result=run(cycle_case)
    assert result['execution_mode'] == 'preview' and not result['completed_moves']
    assert store.path.read_bytes() == before and not server.calls


@pytest.mark.parametrize('key,value', [('ALLOW_PERMANENT_DELETE','true'),('ALLOW_FILESYSTEM_DELETE','true'),
    ('ALLOW_CROSS_FILESYSTEM_MOVES','true'),('ENABLE_SEASON_PRUNING','true'),('MAX_ACTIONS_PER_RUN','11')])
def test_unsafe_policy_refused_before_claim_or_services(cycle_case,key,value):
    store,values,_,server,_=cycle_case; values[key]=value; before=store.path.read_bytes()
    with pytest.raises(ValueError): run(cycle_case)
    assert store.path.read_bytes() == before and not server.calls


def test_storage_failure_keeps_verified_movie_result_and_leaves_tv_outcome_unknown(cycle_case,monkeypatch):
    from app.json_tracking_store import JsonTrackingSession
    store,_,_,server,_=cycle_case
    checkpoint=JsonTrackingSession.checkpoint
    def fail(session):
        journal=session.state.get(KEY,{}).get('journal')
        if journal and journal['library']=='TV' and journal['kind']=='arr_sync':
            session._closed=True
            raise OSError('synthetic uncertain checkpoint')
        return checkpoint(session)
    monkeypatch.setattr(JsonTrackingSession,'checkpoint',fail)
    result=run(cycle_case)
    assert result['result']=='failed' and result['failure_stage']=='storage_revalidation'
    assert [row['library'] for row in result['completed_moves']]==['Movies']
    assert result['pending_operation_present'] is None
    state=json.loads(store.path.read_bytes())
    assert state[KEY]['journal']['kind']=='move' and state[KEY]['journal']['library']=='TV'
    assert sum(method=='PUT' for method,_ in server.calls)==1


def test_opt_in_live_scan_stages_and_restores_season(cycle_case, monkeypatch):
    from app import json_worker_service, tv_season_review
    from app.tv_season_policy import ARCHIVE

    store, values, requests, server, _ = cycle_case
    show = Path(requests['TV'].source_root) / 'Show'
    for season in (1, 2):
        folder = show / f'Season {season}'
        folder.mkdir()
        (folder / 'episode.mkv').write_bytes(b'disposable video')
    (show / 'video.mkv').unlink()
    holding = show.parents[1] / 'TV_seasons_leaving_soon'
    holding.mkdir()
    values.update(ENABLE_TV_SEASON_RETENTION='true', TV_SEASON_HOLDING_PATH=str(holding))
    series = server.records['/api/v3/series/2']
    series['seasons'] = [{'seasonNumber': 1, 'monitored': True}, {'seasonNumber': 2, 'monitored': True}]
    tags = ['one-season']

    def jf_get(path, params):
        if path == '/Users':
            return [{'Id': 'viewer'}]
        return {'TotalRecordCount': 1, 'Items': [{'Id': 'show', 'Type': 'Series',
                'Path': str(show), 'Tags': tags, 'UserData': {'Played': False, 'PlayCount': 0, 'IsFavorite': False}}]}

    monkeypatch.setattr(tv_season_review, 'ScheduledJellyfinGET', lambda **kwargs: jf_get)
    monkeypatch.setattr(json_worker_service, 'settings_snapshot', lambda: values)

    def collect_seasons(session, **kwargs):
        return {'scanned_titles': 1, 'moves': (), 'clock_changes_applied': 0, 'decisions': (),
                'season_titles': ('Show',)}

    now = NOW.replace(tzinfo=timezone.utc)
    options = dict(settings=values, collect=collect_seasons)
    result = run_cycle(store, trigger='manual', now=now, **options)
    assert result['result'] == 'completed'
    assert result['completed_season_moves'] == ({'title': 'Show', 'season': 1, 'restored': False},)
    assert (holding / 'Show' / 'Season 1' / 'episode.mkv').is_file()
    assert (show / 'Season 2' / 'episode.mkv').is_file()
    assert json.loads(store.path.read_bytes())[ARCHIVE]['TV/Show/1']['previous_monitoring'] is True
    assert server.records['/api/v3/series/2']['seasons'][0]['monitored'] is False

    tags.append('keep-all')
    result = run_cycle(store, trigger='scheduled', now=now + timedelta(hours=2), **options)
    assert result['result'] == 'completed'
    assert result['completed_season_moves'] == ({'title': 'Show', 'season': 1, 'restored': True},)
    assert (show / 'Season 1' / 'episode.mkv').is_file()
    assert not json.loads(store.path.read_bytes())[ARCHIVE]
    assert server.records['/api/v3/series/2']['seasons'][0]['monitored'] is True
    assert sum(method == 'PUT' for method, _ in server.calls) == 2
