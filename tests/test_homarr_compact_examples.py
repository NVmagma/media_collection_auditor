"""Opt-in examples stay synchronized; fixture filters precede the ten-row cap."""
import json
from pathlib import Path
import pytest
from scripts.build_homarr_compact_examples import outputs,ROOT,VARIANTS
from scripts.integration_widget_fixture import create_fixture_app

TOKEN='synthetic_compact_widget_token_01234567890123456789'
AUTH={'Authorization':'Bearer '+TOKEN}


def test_generated_fragments_and_imports_are_synchronized():
    for name,content in outputs().items():assert (ROOT/name).read_text()==content
    for name,_,view,library in VARIANTS:
        prefix='homarr-'+name+'-compact'
        widget=json.loads((ROOT/(prefix+'-widget.example.json')).read_text())
        assert widget['template']==(ROOT/(prefix+'-template.example.jsx')).read_text()
        request=widget['requests']['titles']
        assert request['method']=='GET' and request['auth']=='inherit' and request['permission']=='view'
        assert request['path']=='/api/v1/titles/'+view and '?' not in request['path']
        if library:assert request['query']=={'library':library}
        assert 'Open in Jellyfin' not in widget['template'] and 'onError' not in widget['template']


@pytest.mark.parametrize('library',['Movies','TV'])
def test_compact_fixture_exercises_each_filtered_leaving_list(tmp_path,monkeypatch,library):
    monkeypatch.setenv('INTEGRATION_API_TOKEN',TOKEN)
    app=create_fixture_app(tmp_path,'compact');client=app.test_client()
    state=tmp_path/'state.json';before=state.read_bytes()
    route='/api/v1/titles/leaving-soon?library='+library
    assert client.get(route).status_code==401
    response=client.get(route,headers=AUTH)
    assert response.status_code==200
    report=response.json
    assert report['library_filter']==library and report['total_records']==12 and len(report['items'])==10
    assert report['truncated'] is True and all(row['library']==library for row in report['items'])
    assert report['items'][2]['poster_url'] is None and report['items'][2]['jellyfin_url'] is None
    assert report['items'][3]['poster_url'] is None
    assert state.read_bytes()==before
    assert client.get('/fixture/poster.png').status_code==200
    assert client.post('/api/run-now',headers=AUTH).status_code==404


@pytest.mark.parametrize('query',['library=bad','library=TV&library=Movies'])
def test_fixture_refuses_invalid_or_repeated_library_filters(tmp_path,monkeypatch,query):
    monkeypatch.setenv('INTEGRATION_API_TOKEN',TOKEN)
    client=create_fixture_app(tmp_path,'compact').test_client()
    assert client.get('/api/v1/titles/leaving-soon?'+query,headers=AUTH).status_code==400
