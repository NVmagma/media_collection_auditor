from datetime import datetime,timezone
from types import SimpleNamespace
import json
import pytest
from app.sqlite_scan_details import project_details,plan_details,LIMIT
from app.sqlite_scheduled_observations import ScheduledRunObservations
from app.sqlite_scheduled_plan import collect_scheduled_plan,LibraryScan,ScannedTitle
from app.sqlite_state import SECTIONS
from app.dashboard_tracking_snapshot import build_scan_view
from app.integration_status import project_scan_capture

NOW=datetime(2026,10,29)

def preparation(count=3):
    state={key:{} for key in SECTIONS}
    state['first_seen']={f'Movie {index}':'2026-10-28' for index in range(count)}
    state['first_seen'][f'Movie {count-1}']='2025-01-01'
    titles=[ScannedTitle(key,'Waiting',30,{}) for key in state['first_seen']]
    plan=collect_scheduled_plan(snapshot=state,revision=0,libraries=['Movies'],now=NOW,
        maximum_actions=1,scan_library=lambda name:LibraryScan(True,titles))
    return SimpleNamespace(plan=plan,bindings=tuple(SimpleNamespace(media_key=key,folder=key)
        for key in state['first_seen']),clock_proposal=None)

def test_real_plan_explains_waiting_and_prioritizes_selected_move_past_limit():
    prepared=preparation(150);details=plan_details(prepared)
    assert details['total_records']==150 and len(details['items'])==LIMIT and details['truncated']
    rows={row['title']:row for row in details['items']}
    assert rows['Movie 149']['reason_code']=='waiting_expired'
    assert rows['Movie 0']['reason_code']=='waiting_period'
    assert rows['Movie 149']['outcome']=='planned'
    actual=plan_details(prepared,completed=({'media_key':'Movie 149'},))
    assert next(row for row in actual['items'] if row['title']=='Movie 149')['outcome']=='completed'

def test_uncertain_move_is_never_reported_completed():
    report=plan_details(preparation(),stopped_index=0)
    assert next(row for row in report['items'] if row['title']=='Movie 2')['outcome']=='uncertain'

def test_unknown_fields_and_free_text_never_escape_and_invalid_title_refused():
    report=plan_details(preparation());report['secret']='private-value'
    report['items'][0].update(reason='private-error',path='/private/source',credentials='token-value')
    text=json.dumps(project_details(report))
    assert all(value not in text for value in ('private-value','private-error','/private','token-value'))
    report['items'][0]['title']='../private'
    assert project_details(report) is None

def test_verified_move_survives_later_arr_failure_without_raw_error_or_replay():
    observer=ScheduledRunObservations();when=NOW.replace(tzinfo=timezone.utc)
    def fail():
        observer.record_title_details(plan_details(preparation(),completed=({'media_key':'Movie 2'},)))
        raise RuntimeError('private-url-token')
    with pytest.raises(RuntimeError):observer.run_attempt(scheduled_at=when,execute=fail)
    capture=observer.capture();row=build_scan_view(capture['run'],capture['history'])['latest']
    assert row['group']=='review' and row['title_details']['items'][-1]['outcome']=='completed'
    assert 'private-url-token' not in json.dumps(row)
    assert project_scan_capture(capture)['rows'][0]['title_details'] is None
    detached=observer.history();detached[0]['title_details']['items'].clear()
    assert observer.history()[0]['title_details']['items']
    assert not ScheduledRunObservations().history()

def test_missing_details_remain_unknown():
    assert project_details(None) is None
    assert project_details({'schema_version':1,'total_records':0,'items':[]})['items']==[]
