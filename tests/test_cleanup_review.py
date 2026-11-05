from copy import deepcopy
import pytest
from app.cleanup_review import review
from app.orphan_cleanup import STATE_KEY
from test_integration_api import api
import web


def folder(title='Leftover',library='Movies'):
    return dict(title=title,library=library,media_key=('TV/' if library=='TV' else '')+title,
                stage='Waiting',source_root='/media/'+library,identity=[1,2],root_identity=[1,3],fingerprint='a'*64)


def state(count=1):
    observations={}
    for n in range(count):
        f=folder(f'Leftover {n:03}')
        observations[f['media_key']]=dict(folder=f,first_observed_at='2026-11-04T02:00:00+00:00',
            last_observed_at='2026-11-04T14:00:00+00:00',private='SECRET')
    return {STATE_KEY:dict(schema_version=1,observations=observations,quarantined={}),
            'first_seen':{'Preserved':'2026-01-01'},'unknown':{'private':'SECRET'}}


def history():
    return [dict(worker_mode='json_serialized',started_at='2026-11-04T14:00:00+00:00',title_details=dict(
        schema_version=1,total_records=1,items=[dict(library='TV',title='Unknown files',stage='Waiting',
            destination=None,reason_code='no_video_unknown_files',outcome='skipped',private='SECRET')]))]


def test_observation_uses_saved_interval_not_current_time_and_never_changes_state():
    saved=state(27);before=deepcopy(saved)
    result=review(saved,history())
    assert result['counts']==dict(observing=27,blocked=1,quarantined=0)
    assert len(result['items'])==25 and result['pages']==2
    assert result['items'][0]['hours']==12
    assert 'Waiting for unchanged' in result['items'][0]['reason']
    assert len(review(saved,[],page=2)['items'])==2
    assert review(saved,[],query='026')['matched']==1
    assert review(saved,[],library='TV')['matched']==0
    assert saved==before and 'SECRET' not in str(result)


def test_recorded_grace_does_not_grant_fresh_authority():
    saved=state();row=saved[STATE_KEY]['observations']['Leftover 000']
    row['last_observed_at']='2026-11-05T04:00:00+00:00'
    result=review(saved,[])
    assert result['items'][0]['hours']==24
    assert 'fresh checks still required' in result['items'][0]['reason']


def test_historical_receipt_paths_are_retained_without_current_settings_or_inventory():
    saved=state(0);f=folder('Old Show','TV')
    saved[STATE_KEY]['quarantined']['b'*32]=dict(folder=f,observed_at='2026-11-04T14:00:00+00:00',
        quarantine_path='/old-media/.auditor-orphans',private='SECRET')
    result=review(saved,[],view='quarantined')
    assert result['items'][0]['location']=='/old-media/.auditor-orphans/'+'b'*32
    del saved[STATE_KEY]['quarantined']['b'*32]['quarantine_path']
    assert review(saved,[],view='quarantined')['items'][0]['location'] is None
    assert 'SECRET' not in str(result)


def test_unknown_files_are_explained_without_exposing_raw_record():
    result=review({},history(),view='blocked')
    assert result['matched']==1 and not result['partial']
    assert 'unknown files' in result['items'][0]['reason']
    assert review({},[],view='blocked')['partial']


@pytest.mark.parametrize('args',[{'view':'delete'},{'library':'unknown'},{'page':0},{'page':True},{'query':'x'*256}])
def test_bad_filters_refused(args):
    with pytest.raises(ValueError):review({},[],**args)


def test_bad_record_never_looks_like_empty_healthy_state():
    saved=state();saved[STATE_KEY]['observations']['Leftover 000']['last_observed_at']='invalid'
    with pytest.raises(ValueError):review(saved,[])


def test_route_admin_only_readonly_escaped_and_unavailable(api,monkeypatch):
    client=api[0];saved=state();before=deepcopy(saved)
    monkeypatch.setattr(web,'load_state',lambda:deepcopy(saved))
    monkeypatch.setattr(web,'read_history',lambda limit:history())
    monkeypatch.setattr(web,'load_config',lambda:{'ORPHAN_CLEANUP_ENABLED':'false','DAILY_RUN_TIMEZONE':'America/Los_Angeles'})
    assert client.get('/cleanup-review').status_code==302
    monkeypatch.setattr(web,'current_user',lambda:{'admin':False,'name':'Viewer'})
    assert client.get('/cleanup-review').status_code==403
    monkeypatch.setattr(web,'current_user',lambda:{'admin':True,'name':'Admin'})
    response=client.get('/cleanup-review')
    assert response.status_code==200 and '12.0 / 24 hours' in response.text
    assert 'SECRET' not in response.text and response.headers['Cache-Control']=='no-store'
    assert saved==before
    assert client.get('/cleanup-review?view=blocked').status_code==200
    assert client.post('/cleanup-review').status_code==405
    assert client.get('/cleanup-review?view=blocked&view=observing').status_code==400
    assert client.get('/cleanup-review?directory=/private').status_code==400
    saved[STATE_KEY]['schema_version']=9
    response=client.get('/cleanup-review')
    assert response.status_code==503 and 'empty list' in response.text
    assert 'No matching recorded entries' not in response.text
