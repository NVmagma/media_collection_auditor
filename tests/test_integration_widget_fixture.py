"""Expose only authenticated, read-only widget responses from test data."""
import json
import pytest
from scripts.integration_widget_fixture import create_fixture_app, read_fixture_token

TOKEN = 'disposable_widget_token_01234567890123456789'
AUTH = {'Authorization': 'Bearer ' + TOKEN}


@pytest.mark.parametrize('scenario,code', [('sample', 200), ('empty', 200), ('unavailable', 503)])
def test_fixture_scenarios_preserve_unknown_versus_zero(tmp_path, monkeypatch, scenario, code):
    monkeypatch.setenv('INTEGRATION_API_TOKEN', TOKEN)
    app = create_fixture_app(tmp_path, scenario)
    client = app.test_client()
    state = tmp_path / 'state.json'
    before = state.read_bytes() if state.exists() else None
    assert client.get('/api/v1/summary').status_code == 401
    report = client.get('/api/v1/summary', headers=AUTH)
    assert report.status_code == code
    assert report.json['fixture_only'] is True
    assert report.json['production_authorized'] is False
    assert 'Fixture A' not in report.text and '/fixture/holding' not in report.text
    if scenario == 'sample':
        assert report.json['tracking_counts'] == {'waiting': 2, 'holding': 1, 'keep': 1,
                                                  'removal': 1, 'arr_sync_pending': 1}
    elif scenario == 'empty':
        assert set(report.json['tracking_counts'].values()) == {0}
    else:
        assert report.json['tracking_counts'] is None
    audit = client.get('/api/v1/audit-status', headers=AUTH)
    assert audit.status_code == code
    assert audit.json['freshness_verified'] is False
    assert audit.headers['Cache-Control'] == 'no-store'
    assert (state.read_bytes() if state.exists() else None) == before
    assert client.head('/api/v1/summary', headers=AUTH).data == b''


@pytest.mark.parametrize('route', ['/api/run-now', '/api/rescue', '/settings', '/login', '/api/test-connection/jellyfin'])
def test_fixture_never_imports_or_exposes_actions(tmp_path, monkeypatch, route):
    monkeypatch.setenv('INTEGRATION_API_TOKEN', TOKEN)
    client = create_fixture_app(tmp_path, 'empty').test_client()
    assert client.post(route, headers=AUTH).status_code == 404


def test_post_and_query_token_cannot_mutate_or_authenticate(tmp_path, monkeypatch):
    monkeypatch.setenv('INTEGRATION_API_TOKEN', TOKEN)
    client = create_fixture_app(tmp_path, 'empty').test_client()
    assert client.get('/api/v1/summary?token=' + TOKEN).status_code == 401
    assert client.post('/api/v1/summary', headers=AUTH).status_code == 405
    monkeypatch.delenv('INTEGRATION_API_TOKEN')
    assert client.get('/api/v1/audit-status', headers=AUTH).status_code == 404


def test_existing_fixture_state_is_never_overwritten(tmp_path):
    state = tmp_path / 'state.json'
    state.write_text('retained')
    with pytest.raises(ValueError):
        create_fixture_app(tmp_path, 'sample')
    assert state.read_text() == 'retained'


@pytest.mark.parametrize('raw', [b'short', b'x' * 257, b'x' * 32 + b'\n\n', b'x' * 32 + b' secret'])
def test_credential_file_requires_valid_bounded_token(tmp_path, raw):
    token = tmp_path / 'token'
    token.write_bytes(raw)
    with pytest.raises(ValueError):
        read_fixture_token(token)


def test_private_token_file_and_symlink_rejection(tmp_path):
    token = tmp_path / 'token'
    token.write_text(TOKEN + '\n')
    token.chmod(0o600)
    assert read_fixture_token(token) == TOKEN
    alias = tmp_path / 'alias'
    alias.symlink_to(token)
    with pytest.raises(OSError):
        read_fixture_token(alias)


def test_container_entrypoint_installs_hard_expiry_without_starting_worker(tmp_path, monkeypatch):
    from scripts import integration_widget_fixture as module
    calls = []
    monkeypatch.setattr(module.Path, 'is_file', lambda self: str(self) == '/.dockerenv')
    monkeypatch.setattr(module, 'read_fixture_token', lambda path: TOKEN)
    monkeypatch.setattr(module.signal, 'signal', lambda number, handler: calls.append(('handler', handler)))
    monkeypatch.setattr(module.signal, 'alarm', lambda seconds: calls.append(('alarm', seconds)))
    monkeypatch.setattr(module, 'serve_fixture', lambda app, seconds: calls.append(('serve', seconds)))
    monkeypatch.setenv('INTEGRATION_API_TOKEN', '')
    assert module.main(['--token-file', str(tmp_path / 'token')]) == 0
    assert [item for item in calls if item[0] != 'handler'] == [('alarm', 900), ('serve', 900), ('alarm', 0)]

    def exit_process(code):
        raise SystemExit(code)

    monkeypatch.setattr(module.os, '_exit', exit_process)
    handler = next(item[1] for item in calls if item[0] == 'handler')
    with pytest.raises(SystemExit) as expired:
        handler(None, None)
    assert expired.value.code == 0


@pytest.mark.parametrize('seconds', ['0', '3601'])
def test_unbounded_or_invalid_lifetime_refused_before_credential_read(monkeypatch, seconds):
    from scripts import integration_widget_fixture as module
    monkeypatch.setattr(module.Path, 'is_file', lambda self: True)
    monkeypatch.setattr(module, 'read_fixture_token', lambda path: pytest.fail('No credential read'))
    assert module.main(['--token-file', '/unused', '--lifetime-seconds', seconds]) == 2


@pytest.mark.parametrize('scenario,code,count', [('sample', 200, 2), ('empty', 200, 0), ('unavailable', 503, None)])
@pytest.mark.parametrize('view', ['oldest-waiting', 'leaving-soon'])
def test_title_fixture_views_share_production_projection(tmp_path, monkeypatch, scenario, code, count, view):
    monkeypatch.setenv('INTEGRATION_API_TOKEN', TOKEN)
    client = create_fixture_app(tmp_path, scenario).test_client()
    path = '/api/v1/titles/' + view
    assert client.get(path).status_code == 401
    assert client.post(path, headers=AUTH).status_code == 405
    response = client.get(path, headers=AUTH)
    assert response.status_code == code
    report = response.json
    assert report['fixture_only'] is True
    assert report['production_authorized'] is False
    assert report['freshness_verified'] is False
    assert response.headers['Cache-Control'] == 'no-store'
    if scenario == 'unavailable':
        assert report['items'] is None
    else:
        assert len(report['items']) == (1 if scenario == 'sample' and view == 'leaving-soon' else count)
        for item in report['items']:
            assert item['transition_authorized'] is False
            assert set(item) == {'title', 'library', 'stage', 'since',
                                 'estimated_removal_stage_at', 'transition_authorized'}
    assert '/fixture/holding' not in response.text


@pytest.mark.parametrize('view', ['oldest-waiting', 'leaving-soon'])
def test_dense_fixture_exercises_ten_rows_and_truncation(tmp_path, monkeypatch, view):
    monkeypatch.setenv('INTEGRATION_API_TOKEN', TOKEN)
    client = create_fixture_app(tmp_path, 'titles').test_client()
    report = client.get('/api/v1/titles/' + view, headers=AUTH).json
    assert len(report['items']) == 10
    assert report['total_records'] == 12
    assert report['truncated'] is True
    assert report['items'][0]['title'].endswith('01')
    assert report['items'][-1]['title'].endswith('10')


def test_artwork_fixture_serves_only_synthetic_public_image_and_link(tmp_path, monkeypatch):
    monkeypatch.setenv('INTEGRATION_API_TOKEN', TOKEN)
    client = create_fixture_app(tmp_path, 'artwork').test_client()
    assert client.get('/api/v1/titles/oldest-waiting').status_code == 401
    report = client.get('/api/v1/titles/oldest-waiting', headers=AUTH).json
    assert len(report['items']) == 10
    assert report['items'][0]['poster_url'] == 'http://localhost/fixture/poster.png'
    assert report['items'][2]['match_status'] == 'ambiguous'
    assert report['items'][2]['poster_url'] is None
    assert report['items'][2]['jellyfin_url'] is None
    assert report['items'][3]['poster_url'] is None
    assert report['items'][3]['jellyfin_url']
    assert report['items'][4]['match_status'] == 'unmatched'
    image = client.get('/fixture/poster.png')
    assert image.status_code == 200
    assert image.content_type == 'image/png'
    assert image.data.startswith(b'\x89PNG\r\n\x1a\n')
    assert len(image.data) < 1000
    assert client.head('/fixture/poster.png').data == b''
    assert client.post('/fixture/poster.png').status_code == 405
    assert b'Synthetic Jellyfin destination reached' in client.get('/fixture/jellyfin').data
    assert TOKEN not in json.dumps(report)
