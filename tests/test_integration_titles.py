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
    assert client.post(url, headers=AUTH).status_code == 401
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
