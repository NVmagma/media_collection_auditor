"""Title lists are opt-in tracking projections, never collection or actions."""
import json
import pytest
from app.integration_status import read_tracking_titles
from test_integration_api import api, AUTH


def test_oldest_waiting_filters_retained_stage_records_and_limits(tmp_path):
    path = tmp_path / 'state.json'
    state = {'first_seen': {f'Movie {n:02}': f'2024-01-{n+1:02}' for n in range(15)},
             'queued': {'Movie 00': '2024-02-01'},
             'keep_seen': {'Movie 01': '2024-02-01'},
             'in_removal': {'Movie 02': '2024-02-01'}}
    raw = json.dumps(state)
    path.write_text(raw)
    report = read_tracking_titles(path, 'oldest-waiting')
    assert report['total_records'] == 12
    assert report['truncated'] is True
    assert len(report['items']) == 10
    assert report['items'][0]['title'] == 'Movie 03'
    assert report['items'][-1]['title'] == 'Movie 12'
    assert report['items'][0]['estimated_removal_stage_at'] is None
    assert path.read_text() == raw


def test_holding_estimate_is_not_a_deletion_deadline(tmp_path):
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({'queued': {'TV/Series A': '2024-01-01T12:00:00'}}))
    report = read_tracking_titles(path, 'leaving-soon', holding_days=9)
    item, = report['items']
    assert item['library'] == 'TV'
    assert item['title'] == 'Series A'
    assert item['estimated_removal_stage_at'] == '2024-01-10T12:00:00'
    assert item['transition_authorized'] is False
    assert report['timestamp_basis'] == 'legacy_local_wall_time'


@pytest.mark.parametrize('raw', [None, '[]', '{"queued":{}}',
    '{"first_seen":{"/private/secret":"2024-01-01"}}',
    '{"first_seen":{"TV/../secret":"2024-01-01"}}',
    '{"first_seen":{"secret":"invalid"}}'])
def test_invalid_or_missing_never_becomes_empty(tmp_path, raw):
    path = tmp_path / 'state.json'
    if raw is not None:
        path.write_text(raw)
    report = read_tracking_titles(path, 'oldest-waiting')
    if raw == '{"queued":{}}':
        assert report['items'] == []
    else:
        assert report['status'] == 'unavailable'
        assert report['items'] is None
    assert 'secret' not in json.dumps(report)


def test_empty_is_available(tmp_path):
    path = tmp_path / 'state.json'
    path.write_text('{}')
    report = read_tracking_titles(path, 'leaving-soon')
    assert report['items'] == []
    assert report['total_records'] == 0
    assert report['freshness_verified'] is False


@pytest.mark.parametrize('view', ['oldest-waiting', 'leaving-soon'])
def test_title_routes_require_bearer_and_explicit_opt_in(api, monkeypatch, view):
    client, path = api
    url = '/api/v1/titles/' + view
    monkeypatch.delenv('INTEGRATION_API_TITLE_DETAILS', raising=False)
    assert client.get(url).status_code == 401
    assert client.get(url, headers=AUTH).status_code == 404
    monkeypatch.setenv('INTEGRATION_API_TITLE_DETAILS', 'true')
    monkeypatch.setattr('web.load_config', lambda: {'HOLDING_DAYS': '9'})
    raw = path.read_bytes()
    response = client.get(url, headers=AUTH)
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Vary'] == 'Authorization'
    assert path.read_bytes() == raw
    assert client.post(url, headers=AUTH).status_code == 405
    monkeypatch.setenv('READ_ONLY_API_SERVICE', 'true')
    assert client.get(url, headers=AUTH).status_code == 200


def test_holding_uses_saved_configuration_override(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv('INTEGRATION_API_TITLE_DETAILS', 'true')
    monkeypatch.setenv('HOLDING_DAYS', '3')
    monkeypatch.setattr('web.load_config', lambda: {'HOLDING_DAYS': '9'})
    response = client.get('/api/v1/titles/leaving-soon', headers=AUTH)
    assert response.json['items'][0]['estimated_removal_stage_at'] == '2024-01-10T00:00:00'


@pytest.mark.parametrize('days', [0, -1, True, '7', 36501])
def test_invalid_duration_returns_unknown_not_default(tmp_path, days):
    path = tmp_path / 'state.json'
    path.write_text('{}')
    assert read_tracking_titles(path, 'leaving-soon', holding_days=days)['items'] is None


def test_invalid_saved_duration_returns_full_unavailable_schema(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv('INTEGRATION_API_TITLE_DETAILS', 'true')
    monkeypatch.setattr('web.load_config', lambda: {'HOLDING_DAYS': 'invalid'})
    response = client.get('/api/v1/titles/leaving-soon', headers=AUTH)
    assert response.status_code == 503
    assert response.json['items'] is None
    assert response.json['freshness_verified'] is False


def test_one_snapshot_and_stable_ties(tmp_path, monkeypatch):
    import app.integration_status as module
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({'first_seen': {'Z': '2024-01-01', 'A': '2024-01-01',
                                               'TV/A': '2024-01-01'}}))
    original = module.read_json_dashboard_snapshot
    calls = []
    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(True)
        path.write_text('{}')
        return result
    monkeypatch.setattr(module, 'read_json_dashboard_snapshot', capture)
    report = module.read_tracking_titles(path, 'oldest-waiting')
    assert calls == [True]
    assert [(i['library'], i['title']) for i in report['items']] == [
        ('Movies', 'A'), ('Movies', 'Z'), ('TV', 'A')]


@pytest.mark.parametrize('view', ['oldest-waiting', 'leaving-soon'])
def test_unapproved_sqlite_titles_never_fall_back_to_json(api, monkeypatch, view):
    client, path = api
    original = path.read_bytes()
    monkeypatch.setenv('AUDITOR_STATE_BACKEND', 'unsupported')
    monkeypatch.setenv('INTEGRATION_API_TITLE_DETAILS', 'true')
    response = client.get('/api/v1/titles/' + view, headers=AUTH)
    assert response.status_code == 503
    assert response.json['storage_authority'] == 'unavailable'
    assert response.json['items'] is None
    assert 'private-title' not in response.text
    assert path.read_bytes() == original


def test_library_filter_applies_before_ten_record_limit(tmp_path):
    path=tmp_path/'state.json'
    state={'queued':{**{f'Movie {n:02}':'2024-01-01' for n in range(20)},
                     'TV/Series A':'2024-02-01'}}
    path.write_text(json.dumps(state)); before=path.read_bytes()
    result=read_tracking_titles(path,'leaving-soon',library='TV')
    assert result['library_filter']=='TV' and result['total_records']==1
    assert result['truncated'] is False and result['items'][0]['title']=='Series A'
    assert result['items'][0]['transition_authorized'] is False
    assert path.read_bytes()==before


@pytest.mark.parametrize('query',['library=TV','library=Movies'])
def test_authenticated_library_filter_route(api,monkeypatch,query):
    client,path=api
    monkeypatch.setenv('INTEGRATION_API_TITLE_DETAILS','true')
    path.write_text(json.dumps({'queued':{'Movie':'2024-01-01','TV/Series':'2024-01-02'}}))
    response=client.get('/api/v1/titles/leaving-soon?'+query,headers=AUTH)
    assert response.status_code==200
    assert response.json['total_records']==1
    assert response.json['items'][0]['library']==query.split('=')[1]


@pytest.mark.parametrize('query',['library=invalid','library=','library=TV&library=Movies'])
def test_invalid_library_filter_is_refused(api,monkeypatch,query):
    client,_=api; monkeypatch.setenv('INTEGRATION_API_TITLE_DETAILS','true')
    assert client.get('/api/v1/titles/leaving-soon?'+query,headers=AUTH).status_code==400



def test_homarr_tv_examples_keep_query_parameters_separate_from_path():
    from pathlib import Path
    base=Path(__file__).resolve().parents[1]/'examples'/'integrations'
    for name in ('homarr-tv-leaving-soon-requests.example.json','homarr-tv-leaving-soon-widget.example.json'):
        data=json.loads((base/name).read_text())
        request=data.get('requests',data)['titles']
        assert request['path']=='/api/v1/titles/leaving-soon'
        assert request['query']=={'library':'TV'}
        assert request['auth']=='inherit'
