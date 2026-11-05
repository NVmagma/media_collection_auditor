"""Aggregate coverage is read-only and never turns missing input into zero gaps."""
import json
import pytest
from tests.test_integration_api import api, AUTH, TOKEN
import web


@pytest.fixture
def coverage_api(api, tmp_path, monkeypatch):
    client, state = api
    media = tmp_path/'media'
    for library in ('Movies','TV'):
        for suffix in ('','_hold','_removal','_keep'):
            (media/(library+suffix)).mkdir(parents=True)
        (media/library/'Private same title').mkdir()
    state.write_text(json.dumps({'first_seen':{'Private same title':'2024-01-01','TV/Orphan':'2024-01-01'}}))
    config = {'MEDIA_PATH':str(media),'ENABLE_MOVIES':'true','ENABLE_TV':'true'}
    monkeypatch.setattr(web,'load_config',lambda:dict(config))
    monkeypatch.setenv('AUDITOR_STATE_BACKEND','json')
    monkeypatch.setenv('INTEGRATION_API_COVERAGE','true')
    return client,state,media,config


def test_coverage_auth_and_opt_in_precede_inventory(coverage_api, monkeypatch):
    client,*_ = coverage_api
    monkeypatch.setattr(web,'filesystem_stages',lambda *a,**k:pytest.fail('No inventory'))
    assert client.get('/api/v1/coverage').status_code == 401
    monkeypatch.setenv('INTEGRATION_API_COVERAGE','false')
    assert client.get('/api/v1/coverage',headers=AUTH).status_code == 404


def test_coverage_matches_review_projection_without_private_details(coverage_api):
    client,state,media,config = coverage_api
    before = state.read_bytes()
    response = client.get('/api/v1/coverage',headers=AUTH)
    assert response.status_code == 200
    report = response.json
    expected = web.summarize_dashboard_clocks(web.load_state(),*web.filesystem_stages(web.load_state(),config),libraries=['Movies','TV'])
    assert report['rows'] == expected['rows']
    assert report['missing_dates'] == 1 and report['records_without_stage_folder'] == 1
    assert report['freshness_verified'] is False and report['filesystem_snapshot_atomic'] is False
    assert report['media_actions_authorized'] is False
    assert report['storage_authority'] == 'json'
    assert all(secret not in response.text for secret in (TOKEN,str(media),'Private same title','Orphan'))
    assert response.headers['Cache-Control'] == 'no-store'
    assert state.read_bytes() == before


def test_filter_limits_inventory_and_counts(coverage_api, monkeypatch):
    client,state,media,config = coverage_api
    (media/'TV').rename(media/'HiddenTV')
    response = client.get('/api/v1/coverage?library=Movies',headers=AUTH)
    assert response.status_code == 200
    assert len(response.json['rows']) == 4
    assert response.json['missing_dates'] == 0
    assert all(row['library']=='Movies' for row in response.json['rows'])
    monkeypatch.setattr(web,'filesystem_stages',lambda *a,**k:pytest.fail('Invalid query must not scan'))
    for query in ('library=Movie','library=Movies&library=TV','library='):
        assert client.get('/api/v1/coverage?'+query,headers=AUTH).status_code == 400


def test_unavailable_directory_has_unknown_aggregate(coverage_api):
    client,state,media,_ = coverage_api
    (media/'Movies_hold').rmdir()
    response = client.get('/api/v1/coverage',headers=AUTH)
    assert response.status_code == 503
    assert response.json['missing_dates'] is None
    row = next(row for row in response.json['rows'] if row['library']=='Movies' and row['stage']=='Holding')
    assert row['status']=='directory_unavailable' and row['folders'] is None


def test_disabled_library_and_no_enabled_libraries_are_explicit(coverage_api):
    client,_,_,config = coverage_api
    config['ENABLE_TV']='false'
    assert client.get('/api/v1/coverage?library=TV',headers=AUTH).json['status']=='library_disabled'
    config['ENABLE_MOVIES']='false'
    response = client.get('/api/v1/coverage',headers=AUTH)
    assert response.status_code == 503 and response.json['status']=='no_enabled_libraries'


@pytest.mark.parametrize('mutation',['remove','replace','change'])
def test_state_change_during_inventory_invalidates_whole_report(coverage_api,monkeypatch,mutation):
    client,state,_,_ = coverage_api
    original = web.filesystem_stages
    def scan(*a,**kw):
        result = original(*a,**kw)
        if mutation=='remove':state.unlink()
        elif mutation=='change':state.write_text('{}')
        else:
            other=state.with_name('other.json');other.write_bytes(state.read_bytes());other.replace(state)
        return result
    monkeypatch.setattr(web,'filesystem_stages',scan)
    response=client.get('/api/v1/coverage',headers=AUTH)
    assert response.status_code==503 and response.json['rows'] is None


def test_missing_or_symlink_source_never_becomes_empty(coverage_api):
    client,state,_,_ = coverage_api
    raw=state.read_bytes();state.unlink()
    assert client.get('/api/v1/coverage',headers=AUTH).status_code==503
    assert not state.exists()
    target=state.with_name('target.json');target.write_bytes(raw);state.symlink_to(target)
    assert client.get('/api/v1/coverage',headers=AUTH).status_code==503
    assert target.read_bytes()==raw


def test_inventory_bound_is_unknown_not_partial(coverage_api,monkeypatch):
    client,state,media,config = coverage_api
    stages,warnings=web.filesystem_stages(web.load_state(),config,max_entries=0)
    assert warnings
    assert stages['Waiting']==[]
    assert str(media) not in client.get('/api/v1/coverage',headers=AUTH).text


def test_changed_settings_invalidates_whole_report(coverage_api,monkeypatch):
    client,state,media,config = coverage_api
    original=web.filesystem_stages
    def scan(*a,**kw):
        result=original(*a,**kw);config['ENABLE_TV']='false';return result
    monkeypatch.setattr(web,'filesystem_stages',scan)
    response=client.get('/api/v1/coverage',headers=AUTH)
    assert response.status_code==503 and response.json['rows'] is None




def test_unsupported_backend_never_uses_json(coverage_api,monkeypatch):
    client,state,*_=coverage_api
    monkeypatch.setenv('AUDITOR_STATE_BACKEND','unsupported')
    monkeypatch.setattr(web,'filesystem_stages',lambda *a,**k:pytest.fail('No unbound scan'))
    response=client.get('/api/v1/coverage',headers=AUTH)
    assert response.status_code==503 and response.json['rows'] is None
