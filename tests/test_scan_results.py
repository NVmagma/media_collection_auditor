from copy import deepcopy
import pytest
from app.json_worker_service import _title_details
from app.scan_results import browse
from test_integration_api import api
import web


def record():
    decisions=[dict(library='TV' if n%2 else 'Movies',media_key=('TV/' if n%2 else '')+f'Title {n:03}',
        stage='Waiting',destination='Holding',reason='disliked',outcome='proposed') for n in range(241)]
    completed=[dict(library='Movies',media_key='Title 240')]
    pages=[_title_details(decisions,completed,'completed',offset=n) for n in range(0,241,100)]
    return dict(id='a'*32,worker_mode='json_serialized',title_details=pages[0],title_detail_pages=pages,
                started_at='2026-11-04T10:00:00+00:00',dry_run=False,result='completed',private_token='SECRET')


def test_all_rows_search_filters_and_verified_outcomes_beyond_100():
    row=record();before=deepcopy(row)
    assert browse(row)['total']==241
    assert len(browse(row)['items'])==25
    last=browse(row,page=10)
    assert len(last['items'])==16 and not last['partial']
    found=browse(row,query='title 240',library='Movies',outcome='completed')
    assert found['matched']==1 and found['items'][0]['outcome']=='completed'
    assert browse(row,library='TV',outcome='completed')['matched']==0
    assert row==before and 'SECRET' not in str(found)


def test_legacy_is_partial_and_never_infers_completed_from_raw_decisions():
    row=record();del row['title_detail_pages']
    row['json_decisions']=[{'outcome':'completed','title':'Not retained'}]
    result=browse(row)
    assert result['partial'] and result['total']==100
    assert browse(row,query='Title 240')['matched']==0


@pytest.mark.parametrize('kwargs',[{'page':0},{'page':True},{'library':'../private'},{'outcome':'arbitrary'},{'query':'x'*256}])
def test_invalid_filters(kwargs):
    with pytest.raises(ValueError):browse(record(),**kwargs)


def test_corrupt_pages_are_not_silently_incomplete():
    row=record();row['title_detail_pages'].pop()
    with pytest.raises(ValueError):browse(row)


def test_authenticated_page_filters_pagination_and_no_secrets(api,monkeypatch):
    client=api[0]
    monkeypatch.setattr(web,'current_user',lambda:None)
    assert client.get('/scan-results').status_code==302
    monkeypatch.setattr(web,'current_user',lambda:{'admin':False,'name':'Viewer'})
    monkeypatch.setattr(web,'read_history',lambda limit:[record()])
    monkeypatch.setattr(web,'load_config',lambda:{'DAILY_RUN_TIMEZONE':'America/Los_Angeles'})
    response=client.get('/scan-results?q=Title+240&outcome=completed')
    assert response.status_code==200 and 'Title 240' in response.text
    assert 'America/Los_Angeles' in response.text
    assert 'SECRET' not in response.text and response.headers['Cache-Control']=='no-store'
    assert client.get('/scan-results?page=2').status_code==200
    assert client.get('/scan-results?library=TV&library=Movies').status_code==400
    assert client.get('/scan-results?path=/private').status_code==400
    assert client.get('/scan-results?attempt='+'b'*32).status_code==404
