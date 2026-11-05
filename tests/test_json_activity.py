"""Activity and exports share redacted persistent JSON scan observations."""
from copy import deepcopy
import io,json,zipfile
import pytest
from app.json_activity import project_activity,export_activity
from test_integration_api import api,AUTH
import web


def record():
    return dict(worker_mode='json_serialized',started_at='2026-11-04T03:56:29+00:00',finished_at='2026-11-04T03:58:39+00:00',
        result='completed',result_basis='worker_return',moves_completed=4,discovery_changes=32,
        error='DO-NOT-EXPORT-SECRET',json_decisions=[{'private_path':'/private/secret'}],
        title_details=dict(schema_version=1,total_records=3,items=[dict(library='Movies',title='Example (2000)',
            stage='Waiting',destination='Holding',reason_code='disliked',outcome=outcome) for outcome in ('completed','planned','uncertain')]))


def test_projection_keeps_outcomes_distinct_and_drops_unrecognized_private_fields():
    row=record();before=deepcopy(row);events=project_activity([row])
    assert events[0]['status']=='completed' and 'Verified moves: 4' in events[0]['detail']
    assert '32' in events[0]['detail']
    assert [item['status'] for item in events[1:]]==['completed','planned','uncertain']
    raw=export_activity([row]).decode()
    assert 'DO-NOT-EXPORT' not in raw and '/private' not in raw and 'private_path' not in raw
    assert row==before


def test_failed_unknown_counts_are_not_zero_or_verified_success():
    row=record();row.update(result='failed',result_basis='blocked_or_uncertain',moves_completed=None,discovery_changes=None,title_details=None)
    events=project_activity([row])
    assert events[0]['status']=='failed' and 'unknown' in events[0]['detail']
    assert 'Verified moves: 0' not in events[0]['detail']
    assert project_activity([row],0)==[]
    row['started_at']='private unrecognized';row['finished_at']=None
    assert project_activity([row])==[]


def test_limit_and_old_worker_isolation():
    row=record()
    assert len(project_activity([row]*100,limit=12))==12
    row['worker_mode']='unsupported'
    assert project_activity([row])==[]


def page(api,monkeypatch):
    monkeypatch.setenv('AUDITOR_WORKER_MODE','json_serialized')
    monkeypatch.setenv('AUDITOR_STATE_BACKEND','json')
    monkeypatch.setattr(web,'current_user',lambda:{'name':'Admin','admin':True})
    monkeypatch.setattr(web,'read_history',lambda limit:[record()])
    monkeypatch.setattr(web,'ACTION_LOG_FILE','/not-present/legacy-actions.jsonl')
    monkeypatch.setattr(web,'load_config',lambda:{'DRY_RUN':'false','INTEGRATION_API_TOKEN':'DO-NOT-EXPORT-SECRET'})
    return api[0]


def test_logs_jsonl_and_diagnostics_use_same_persisted_source(api,monkeypatch):
    client=page(api,monkeypatch)
    response=client.get('/logs')
    assert response.status_code==200 and 'Verified moves: 4' in response.text and 'Example (2000)' in response.text
    exported=client.get('/logs/export')
    assert exported.status_code==200 and exported.headers['Cache-Control']=='no-store'
    events=[json.loads(line) for line in exported.data.splitlines()]
    assert events==project_activity([record()])
    response=client.get('/logs/diagnostics')
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert archive.read('recent_actions.jsonl')==exported.data
        report=json.loads(archive.read('diagnostics.json'))
        assert report['activity_source']=='persistent_json_scan_history'
        assert 'DO-NOT-EXPORT-SECRET' not in str(archive.read('recent_actions.jsonl'))
        assert 'DO-NOT-EXPORT-SECRET' not in str(report)


def test_api_token_cannot_export_browser_activity(api,monkeypatch):
    client=page(api,monkeypatch);monkeypatch.setattr(web,'current_user',lambda:None)
    for route in ('/logs','/logs/export','/logs/diagnostics'):
        assert client.get(route,headers=AUTH).status_code==302
