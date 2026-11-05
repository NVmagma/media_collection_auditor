"""Offline integration responses distinguish unavailable and empty state."""
import json
import pytest
from app.integration_status import read_tracking_status
from scripts.integration_tracking_status import main


def test_empty_existing_state_is_available_but_not_fresh(tmp_path):
    path = tmp_path / 'state.json'
    path.write_text('{}')
    report = read_tracking_status(path)
    assert report['status'] == 'advisory_only'
    assert set(report['tracking_counts'].values()) == {0}
    assert report['pending_operation_present'] is False
    assert report['freshness_verified'] is False
    assert report['production_authorized'] is False


@pytest.mark.parametrize('raw', [None, '[]', '{"queued":[]}', '{"x":1,"x":2}',
                                '{"keep_seen":{"secret":"invalid"}}'])
def test_unavailable_is_not_reported_as_zero(tmp_path, raw, capsys):
    path = tmp_path / 'secret-state.json'
    if raw is not None:
        path.write_text(raw)
    assert main(['--state', str(path)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report['tracking_counts'] is None
    assert report['pending_operation_present'] is None
    assert report['status'] == 'unavailable'
    assert 'secret' not in json.dumps(report)
    assert not path.exists() if raw is None else path.read_text() == raw


def test_counts_overlap_and_pending_payload_is_not_exposed(tmp_path, monkeypatch):
    path = tmp_path / 'state.json'
    state = {'first_seen': {'secret-title': '2024-01-01'},
             'queued': {'secret-title': '2024-01-02'},
             'legacy_pending_operations': None,
             'unknown': {'api_key': 'secret-token', 'path': '/private/media'}}
    raw = json.dumps(state)
    path.write_text(raw)
    monkeypatch.setenv('AUDITOR_STATE_BACKEND', 'unsupported')
    report = read_tracking_status(path)
    assert report['tracking_counts']['waiting'] == 1
    assert report['tracking_counts']['holding'] == 1
    assert report['pending_operation_present'] is True
    assert report['storage_authority'] == 'json'
    assert 'secret' not in json.dumps(report)
    assert '/private' not in json.dumps(report)
    assert path.read_text() == raw


def test_cli_success_uses_one_captured_snapshot(tmp_path, monkeypatch, capsys):
    import app.integration_status as module
    from app.dashboard_tracking_snapshot import read_json_dashboard_snapshot
    path = tmp_path / 'state.json'
    path.write_text('{"queued":{"A":"2024-01-01"}}')
    calls = []

    def capture(*args, **kwargs):
        calls.append(kwargs)
        snapshot = read_json_dashboard_snapshot(*args, **kwargs)
        path.write_text('{}')
        return snapshot

    monkeypatch.setattr(module, 'read_json_dashboard_snapshot', capture)
    assert main(['--state', str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['tracking_counts']['holding'] == 1
    assert calls == [{'require_existing': True}]


@pytest.mark.parametrize('result', ['completed', 'failed', None, {'secret': True}, '/private/token'])
def test_audit_projection_allowlists_results_and_preserves_unknowns(result):
    from app.integration_status import audit_status_report
    report = audit_status_report({'running': False, 'queued': True, 'rescuing': False,
                                  'last_result': result, 'last_started': '2024-01-01',
                                  'last_finished': '2024-01-01T00:00:00+00:00'})
    assert report['queued'] is True
    assert report['last_result'] == (result if isinstance(result, str) and result in ('completed', 'failed') else None)
    assert report['last_started'] is None
    assert report['last_finished'] == '2024-01-01T00:00:00+00:00'
    assert report['freshness_verified'] is False
