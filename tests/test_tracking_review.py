from copy import deepcopy
import pytest
from app.tracking_review import review
from test_integration_api import api
import web


def stages():
    return dict(Waiting=[dict(library='Movies',title='New'),dict(library='Movies',title='renamed'),
                         dict(library='Movies',title='Duplicate')],
                Holding=[dict(library='Movies',title='Moved'),dict(library='Movies',title='Duplicate')],Keep=[],Removal=[])


def state():
    return dict(first_seen={'Absent':'2020-01-01','Moved':'2020-01-01','Renamed':'2020-01-01',
                           'Conflict':'2020-01-01'},keep_seen={'Conflict':'2020-01-02'},
                arr_sync_pending={'TV/Show':{'root':'PRIVATE','stage':'keep'}})


def history():
    return [dict(worker_mode='json_serialized',started_at='2026-11-04T12:00:00+00:00',
        json_decisions=[dict(media_key='TV/Show',library='TV',stage='Waiting',reason='arr_record_missing',private='SECRET')])]


def run(**kwargs):
    return review(state(),stages(),[],history(),libraries=['Movies','TV'],**kwargs)


def test_distinct_issues_names_and_readonly_projection():
    saved=state();inventory=stages();before=deepcopy((saved,inventory))
    result=review(saved,inventory,[],history(),libraries=['Movies','TV'])
    assert result['complete'] and result['counts']['duplicate_folder']==1
    assert result['counts']['clock_conflict']==1 and result['counts']['near_name']==1
    assert run(kind='other_stage')['items'][0]['title']=='Moved'
    assert 'does not prove media was deleted' in run(kind='missing_folder')['items'][0]['detail']
    assert 'renamed' in run(kind='near_name')['items'][0]['detail']
    assert run(kind='arr',library='TV')['items'][0]['title']=='Show'
    assert 'SECRET' not in str(result) and 'PRIVATE' not in str(result)
    assert (saved,inventory)==before


def test_unavailable_directories_never_become_absence_claims():
    result=review(state(),stages(),['Movies Removal: directory unavailable (PRIVATE)'],[],libraries=['Movies'])
    assert not result['complete'] and result['counts']['missing_folder']==0
    assert result['counts']['coverage']>0 and 'PRIVATE' not in str(result)
    assert 'another lifecycle directory is unavailable' in ' '.join(r['detail'] for r in result['items'])


def test_pagination_filters_and_bounded_results():
    saved={'first_seen':{f'Title {n:03}':'2020-01-01' for n in range(60)}}
    result=review(saved,{},[],[],libraries=['Movies'],kind='missing_folder',page=3)
    assert result['matched']==60 and result['pages']==3 and len(result['items'])==10
    assert run(query='absent')['matched']==1


@pytest.mark.parametrize('args',[{'kind':'delete'},{'library':'unknown'},{'page':0},{'page':True},{'query':'x'*256}])
def test_invalid_filters(args):
    with pytest.raises(ValueError):run(**args)


def test_historical_arr_unavailability_does_not_mean_unmanaged():
    result=review({}, {}, [], [], libraries=['Movies'])
    assert result['arr_partial'] and not result['counts']['arr']
    bad=history();bad[0]['json_decisions'][0]['reason']={'private':'SECRET'}
    result=review({}, {}, [], bad, libraries=['TV'])
    assert result['arr_partial'] and not result['counts']['arr']


def test_route_is_admin_only_and_does_not_mutate_or_call_services(api,monkeypatch):
    client=api[0];saved=state();before=deepcopy(saved)
    monkeypatch.setattr(web,'load_state',lambda:deepcopy(saved))
    monkeypatch.setattr(web,'read_history',lambda limit:history())
    monkeypatch.setattr(web,'filesystem_stages',lambda *a,**k:(stages(),[]))
    monkeypatch.setattr(web,'load_config',lambda:{'ENABLE_MOVIES':'true','ENABLE_TV':'true'})
    assert client.get('/tracking-review').status_code==302
    monkeypatch.setattr(web,'current_user',lambda:{'admin':False,'name':'Viewer'})
    assert client.get('/tracking-review').status_code==403
    monkeypatch.setattr(web,'current_user',lambda:{'admin':True,'name':'Admin'})
    response=client.get('/tracking-review?kind=near_name')
    assert response.status_code==200 and 'renamed' in response.text
    assert response.headers['Cache-Control']=='no-store'
    assert 'SECRET' not in response.text and saved==before
    assert client.post('/tracking-review').status_code==405
    assert client.get('/tracking-review?directory=/private').status_code==400
    assert client.get('/tracking-review?kind=arr&kind=all').status_code==400
    count=[0]
    def changing(*a,**k):
        count[0]+=1
        return (stages() if count[0]==1 else {},[])
    monkeypatch.setattr(web,'filesystem_stages',changing)
    response=client.get('/tracking-review')
    assert response.status_code==503 and 'sources changed' in response.text
    assert 'No matching issues' not in response.text


def test_saved_stage_path_is_used_before_stale_environment(tmp_path,monkeypatch):
    saved=tmp_path/'saved';saved.mkdir();(saved/'Saved title').mkdir()
    old=tmp_path/'old';old.mkdir();(old/'Old title').mkdir()
    monkeypatch.setenv('RADARR_TRANSIENT_PATH',str(old))
    inventory,_=web.filesystem_stages({},dict(ENABLE_MOVIES='true',ENABLE_TV='false',RADARR_TRANSIENT_PATH=str(saved)))
    assert [row['title'] for row in inventory['Waiting']]==['Saved title']
