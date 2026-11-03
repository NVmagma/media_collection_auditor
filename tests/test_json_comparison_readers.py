"""Current JSON dashboard/widget readers preserve a detached migrated snapshot."""
from copy import deepcopy
import json

import pytest
from app import integration_status as status
from app.dashboard_tracking_snapshot import DashboardTrackingSnapshot
from tests.test_integration_api import api, AUTH
import web


@pytest.fixture
def exported(api, monkeypatch):
    client, path = api
    state = {key: {} for key in ('first_seen', 'queued', 'in_removal', 'keep_seen', 'arr_sync_pending')}
    for i in range(541):
        key = ('TV/' if i % 2 else '') + f'Existing title {i:03}'
        state['first_seen'][key] = '2026-01-02T03:04:05'
    state['queued'] = {'Holding movie': '2026-01-03T04:05:06', 'TV/Holding show': '2026-01-04T05:06:07'}
    state['in_removal'] = {'Removal movie': '2026-01-05T06:07:08'}
    state['keep_seen'] = {'TV/Keep show': '2026-01-06T07:08:09'}
    state['extension'] = {'secret': 'private-extension-never-project'}
    path.write_text(json.dumps(state))
    monkeypatch.setenv('AUDITOR_STATE_BACKEND', 'json')
    monkeypatch.setenv('INTEGRATION_API_TITLE_DETAILS', 'true')
    # Reading JSON must not open a database or require a SQLite release binding.
    import app.state_store as stores
    monkeypatch.setattr(stores, 'GuardedSQLiteStateStore', lambda *a, **k: pytest.fail('No SQLite reads'))
    monkeypatch.setattr(status, '_require_sqlite_authority', lambda: pytest.fail('No SQLite binding'))
    return client, path, state


def test_dashboard_snapshot_retains_every_clock_and_unknown_field(exported):
    _, path, state = exported
    raw = path.read_bytes()
    first = status.read_selected_dashboard_state(path)
    assert first == state
    first['first_seen'].clear()
    assert status.read_selected_dashboard_state(path) == state
    assert path.read_bytes() == raw


@pytest.mark.parametrize('library', ['Movies', 'TV'])
@pytest.mark.parametrize('view', ['oldest-waiting', 'leaving-soon'])
def test_widgets_match_same_snapshot_projection_without_inventory_claims(exported, library, view):
    client, path, state = exported
    raw = path.read_bytes()
    snapshot = DashboardTrackingSnapshot('json', None, raw, lambda: None)
    expected = status._project_tracking_titles(lambda: snapshot, view,
        holding_days=7, library_filter=library)
    response = client.get('/api/v1/titles/' + view + '?library=' + library, headers=AUTH)
    assert response.status_code == 200
    for key in ('total_records', 'truncated', 'timestamp_basis', 'view'):
        assert response.json[key] == expected[key]
    assert [{key: row[key] for key in expected_row} for row, expected_row in
            zip(response.json['items'], expected['items'], strict=True)] == expected['items']
    assert all(row['match_status'] == 'disabled' and row['jellyfin_url'] is None
               and row['poster_url'] is None for row in response.json['items'])
    assert response.json['storage_authority'] == 'json'
    assert response.json['freshness_verified'] is False
    assert response.json['production_authorized'] is False
    assert len(response.json['items']) <= 10
    if view == 'oldest-waiting': assert response.json['total_records'] > 100
    assert 'private-extension-never-project' not in response.text
    assert path.read_bytes() == raw


def test_summary_counts_entire_collection_and_never_modifies_dates(exported):
    client, path, state = exported
    before = deepcopy(state), path.read_bytes()
    response = client.get('/api/v1/summary', headers=AUTH)
    assert response.status_code == 200
    assert response.json['tracking_counts'] == {
        'waiting':541, 'holding':2, 'removal':1, 'keep':1, 'arr_sync_pending':0}
    assert 'private-extension-never-project' not in response.text
    assert (status.read_selected_dashboard_state(path), path.read_bytes()) == before


def test_unreadable_json_widgets_stay_unavailable_without_resetting_state(exported):
    client, path, _ = exported
    path.write_bytes(b'{broken')
    for endpoint in ('summary', 'titles/leaving-soon?library=TV'):
        assert client.get('/api/v1/'+endpoint, headers=AUTH).status_code == 503
    assert path.read_bytes() == b'{broken'
    path.unlink()
    assert client.get('/api/v1/summary', headers=AUTH).status_code == 503
    assert not path.exists()


def test_current_dashboard_renders_json_records_and_existing_navigation(exported, monkeypatch):
    client, path, state = exported
    raw = path.read_bytes()
    stages = {key: [] for key in ('Waiting', 'Holding', 'Removal', 'Keep')}
    for stage, section in (('Waiting', 'first_seen'), ('Holding', 'queued'),
                           ('Removal', 'in_removal'), ('Keep', 'keep_seen')):
        for key, since in state[section].items():
            stages[stage].append({'library':'TV' if key.startswith('TV/') else 'Movies',
                'title':key.removeprefix('TV/'), 'since':since})
    monkeypatch.setattr(web, 'current_user', lambda: {'admin':False, 'name':'Fixture viewer'})
    monkeypatch.setattr(web, 'load_config', lambda: {'ENABLE_MOVIES':'true', 'ENABLE_TV':'true',
        'DRY_RUN':'true', 'ALLOW_PERMANENT_DELETE':'false'})
    monkeypatch.setattr(web, 'load_actions', lambda: [])
    monkeypatch.setattr(web, 'filesystem_stages', lambda *a: (deepcopy(stages), []))
    monkeypatch.setattr(web, '_dashboard_signals', lambda *a: None)
    monkeypatch.setattr(web, 'selected_run_snapshot', lambda *a, **k: {
        'storage_authority':'json', 'running':False, 'queued':False, 'status':'unavailable'})
    monkeypatch.setattr(web, 'selected_run_history', lambda *a, **k: [])
    for route in ('/', '/review'):
        response = client.get(route)
        assert response.status_code == 200
        assert b'Existing title 540' in response.data
        assert b'private-extension-never-project' not in response.data
        assert b'/static/dashboard.js' in response.data
        assert b'/static/auditor-badge.png' in response.data
    assert path.read_bytes() == raw
