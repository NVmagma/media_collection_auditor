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
