"""Process-local scan APIs expose bounded projections, never worker authority."""
from datetime import datetime, timezone, timedelta
import pytest
from tests.test_integration_api import api,AUTH,TOKEN
import web
from app.sqlite_scheduled_observations import ScheduledRunObservations


@pytest.fixture
def scans(api,monkeypatch):
    client,state=api
    ticks=iter(datetime(2026,10,27,tzinfo=timezone.utc)+timedelta(seconds=n) for n in range(1000))
    observer=ScheduledRunObservations(clock=lambda:next(ticks))
    observer.observe_cycle(next_run=datetime(2026,10,28,tzinfo=timezone.utc),status='waiting')
    monkeypatch.setattr(web,'selected_scan_capture',observer.capture)
    return client,state,observer


def attempt(observer,success=True):
    if success:
        return observer.run_attempt(scheduled_at=datetime(2026,10,27,tzinfo=timezone.utc),dry_run=True,
            execute=lambda:{'status':'scheduled_preview_complete','proposed_moves':('private-title',),'discovery_changes':2,
                            'secret':'private-token-never-output'})
    def fail():raise RuntimeError('private-token-never-output')
    with pytest.raises(RuntimeError):observer.run_attempt(scheduled_at=datetime(2026,10,27,tzinfo=timezone.utc),dry_run=True,execute=fail)


def test_history_auth_filter_pagination_and_safe_projection(scans):
    client,state,observer=scans
    before=state.read_bytes()
    for success in (True,False,True):attempt(observer,success)
    assert client.get('/api/v1/scan-history').status_code==401
    response=client.get('/api/v1/scan-history?page_size=2',headers=AUTH)
    assert response.status_code==200
    assert len(response.json['items'])==2 and response.json['total_records']==3 and response.json['has_more']
    assert response.json['history_scope']=='current_process' and not response.json['history_persistent']
    assert response.json['skipped_title_count'] is None and response.json['blocked_title_count'] is None
    assert response.headers['Cache-Control']=='no-store'
    assert all(value not in response.text for value in (TOKEN,'private-title','private-token-never-output'))
    assert len(client.get('/api/v1/scan-history?page_size=2&page=2',headers=AUTH).json['items'])==1
    review=client.get('/api/v1/scan-history?outcome=review',headers=AUTH).json
    assert review['total_records']==1 and review['items'][0]['group']=='review'
    assert state.read_bytes()==before


@pytest.mark.parametrize('query',['page=0','page=-1','page=101','page=1&page=2','page_size=21','page_size=x','page_size=1.0','outcome=failed','outcome=all&outcome=review'])
def test_invalid_query_precedes_coordinator(scans,monkeypatch,query):
    client,*_=scans
    monkeypatch.setattr(web,'selected_scan_capture',lambda:pytest.fail('No capture'))
    assert client.get('/api/v1/scan-history?'+query,headers=AUTH).status_code==400


def test_proposals_are_recorded_preview_counts_not_actions(scans):
    client,_,observer=scans
    empty=client.get('/api/v1/proposals',headers=AUTH).json
    assert empty['latest_attempt'] is None and empty['moves_proposed'] is None
    attempt(observer)
    response=client.get('/api/v1/proposals',headers=AUTH)
    assert response.status_code==200 and response.json['preview_completed']
    assert response.json['moves_proposed']==1 and response.json['discovery_changes']==2
    assert response.json['proposal_kind']=='counts_only' and not response.json['per_title_details_available']
    assert not response.json['media_actions_authorized'] and not response.json['freshness_verified']
    attempt(observer,False)
    failed=client.get('/api/v1/proposals',headers=AUTH).json
    assert failed['moves_proposed'] is None and failed['preview_completed'] is False
    assert failed['latest_attempt']['group']=='review'


def test_running_is_not_completed_and_prior_proposal_is_labelled(scans):
    client,_,observer=scans
    attempt(observer)
    def execute():
        report=client.get('/api/v1/proposals',headers=AUTH).json
        assert report['current']['state']=='Running'
        assert report['proposal_scope']=='latest_recorded_attempt'
        assert report['latest_attempt']['group']=='completed'
        assert len(observer.capture()['history'])==1
        return {'status':'scheduled_preview_complete'}
    observer.run_attempt(scheduled_at=datetime(2026,10,27,tzinfo=timezone.utc),dry_run=True,execute=execute)


def test_restart_and_sidecar_do_not_reconstruct_history(scans,monkeypatch):
    client,_,observer=scans
    attempt(observer)
    monkeypatch.setattr(web,'selected_scan_capture',ScheduledRunObservations().capture)
    response=client.get('/api/v1/scan-history',headers=AUTH)
    assert response.status_code==503 and response.json['items'] is None
    monkeypatch.setenv('READ_ONLY_API_SERVICE','true')
    monkeypatch.setattr(web,'selected_scan_capture',lambda:pytest.fail('No sidecar coordinator'))
    for route in ('scan-history','proposals'):
        assert client.get('/api/v1/'+route,headers=AUTH).status_code==503


def test_capture_detachment_bounded_and_one_locked_observation(scans):
    _,_,observer=scans
    for _ in range(102):attempt(observer)
    capture=observer.capture()
    assert len(capture['history'])==100
    assert capture['run']['last_started']==capture['history'][0]['started_at']
    capture['history'].clear();capture['run']['last_result']='private'
    assert len(observer.capture()['history'])==100
    assert observer.report()['last_result']=='completed'


def test_unsupported_legacy_backend_has_no_json_history_fallback(api,monkeypatch):
    client,_=api
    monkeypatch.setenv('AUDITOR_STATE_BACKEND','json')
    monkeypatch.setattr(web,'read_history',lambda *a:pytest.fail('No legacy history fallback'))
    assert client.get('/api/v1/scan-history',headers=AUTH).status_code==503


def test_malformed_unknown_fields_and_counts_are_not_projected(scans,monkeypatch):
    client,_,observer=scans
    attempt(observer)
    capture=observer.capture()
    capture['history'][0].update(moves_proposed=True,result_basis={'secret':'never'},trigger={'secret':'never'},private='never')
    capture['history'].append('malformed')
    monkeypatch.setattr(web,'selected_scan_capture',lambda:capture)
    response=client.get('/api/v1/scan-history',headers=AUTH)
    assert response.json['history_partial'] is True
    assert response.json['items'][0]['moves_proposed'] is None
    assert 'never' not in response.text


def test_selected_capture_verifies_binding_before_and_after(monkeypatch):
    import integration_status as selected
    import app.sqlite_scheduled_observations as observations
    observer=ScheduledRunObservations()
    observer.observe_cycle(next_run=datetime(2026,10,28,tzinfo=timezone.utc),status='waiting')
    monkeypatch.setenv('AUDITOR_STATE_BACKEND','sqlite')
    monkeypatch.setattr(observations,'COORDINATOR',observer)
    calls=[]
    monkeypatch.setattr(selected,'_require_sqlite_authority',lambda:calls.append('checked'))
    assert selected.selected_scan_capture()['history']==[]
    assert calls==['checked','checked']
    calls.clear()
    def gate():
        calls.append('checked')
        if len(calls)==2:raise RuntimeError('private')
    monkeypatch.setattr(selected,'_require_sqlite_authority',gate)
    assert selected.selected_scan_capture() is None
