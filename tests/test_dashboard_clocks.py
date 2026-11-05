"""Clock display never fabricates lifecycle dates or rewrites stored state."""
from datetime import datetime,timezone
from copy import deepcopy
from app.dashboard_tracking_snapshot import lifecycle_clock,observation_datetime


def test_naive_dates_keep_wall_time_and_format_minutes():
    result=lifecycle_clock('2026-10-20T11:30:59.123',limit=7,now=datetime(2026,10,23,12))
    assert result['since_display']=='10/20/2026 11:30'
    assert result['elapsed_days']==3 and result['deadline_days']==4
    assert result['next_review_date']=='2026-10-27' and result['due'] is False
    assert result['since_basis']=='Local wall time as recorded'


def test_offset_removal_clock_does_not_become_unknown():
    result=lifecycle_clock('2026-10-20T11:30:00+00:00',limit=7,now=datetime(2026,10,28,tzinfo=timezone.utc))
    assert result['elapsed_days']==7 and result['deadline_days']==0 and result['due']


def test_missing_invalid_and_future_dates_are_distinct():
    assert lifecycle_clock(None)['since_display']=='Not yet tracked'
    invalid=lifecycle_clock('private-value-not-a-date')
    assert invalid['since_display']=='Invalid saved date' and 'private-value' not in str(invalid)
    future=lifecycle_clock('2030-01-01T00:00:00',limit=7,now=datetime(2026,1,1))
    assert future['clock_status']=='future' and future['elapsed_days'] is None and not future['due']


def test_process_observations_include_recorded_utc_offset():
    assert observation_datetime('2026-10-27T09:00:00Z')=='10/27/2026 09:00 UTC+00:00'
    assert observation_datetime(None)=='Not recorded in this process'


def test_process_observation_uses_configured_zone_without_reinterpreting_naive_dates():
    assert observation_datetime('2026-10-27T09:00:00Z','America/Los_Angeles')=='10/27/2026 02:00 America/Los_Angeles'
    assert observation_datetime('2026-10-27T09:00:00','America/Los_Angeles')=='10/27/2026 09:00'


def test_dashboard_removal_age_uses_offset_and_preserves_saved_state(monkeypatch):
    import os
    import web
    from datetime import timedelta
    since=(datetime.now(timezone.utc)-timedelta(days=3,hours=1)).isoformat()
    state={'in_removal':{'Example':since}}
    before=deepcopy(state)
    stages={'Waiting':[],'Holding':[],'Keep':[],
        'Removal':[{'title':'Example','library':'Movies','since':since}]}
    monkeypatch.setattr(web,'load_actions',lambda:[])
    monkeypatch.setattr(web,'load_state',lambda:state)
    monkeypatch.setattr(web,'load_config',lambda:{'REMOVAL_DAYS':'7','ALLOW_PERMANENT_DELETE':'false'})
    monkeypatch.setattr(web,'filesystem_stages',lambda *_:(stages,[]))
    monkeypatch.setattr(web,'_dashboard_signals',lambda _:None)
    monkeypatch.setattr(web,'render_template',lambda *args,**kwargs:kwargs)
    with web.app.test_request_context('/'):
        result=web.dashboard()
    item=result['stages']['Removal'][0]
    assert item['days_left']==4 and item['elapsed_days']==3
    assert item['decision']=='blocked' and result['preview']==[]
    assert state==before


def test_zero_day_wait_is_not_silently_changed_to_one_day():
    result=lifecycle_clock('2026-10-27T11:30:00',limit=0,now=datetime(2026,10,27,12))
    assert result['due'] and result['deadline_days']==0 and result['next_review_display']=='10/27/2026'


def test_invalid_duration_never_crashes_dashboard_or_proposes_a_move(monkeypatch):
    import web
    since='2026-01-01T00:00:00'
    stages={'Waiting':[{'title':'Example','library':'Movies','since':since}],
        'Holding':[],'Removal':[],'Keep':[]}
    monkeypatch.setattr(web,'load_actions',lambda:[])
    monkeypatch.setattr(web,'load_state',lambda:{'first_seen':{'Example':since}})
    monkeypatch.setattr(web,'load_config',lambda:{'MOVIE_WAIT_DAYS':'bad-duration'})
    monkeypatch.setattr(web,'filesystem_stages',lambda *_:(stages,[]))
    monkeypatch.setattr(web,'_dashboard_signals',lambda _:{'Movies':{'example':{}}})
    monkeypatch.setattr(web,'render_template',lambda *args,**kwargs:kwargs)
    with web.app.test_request_context('/'):result=web.dashboard()
    item=result['stages']['Waiting'][0]
    assert item['deadline_days'] is None and item['decision']=='unknown'
    assert result['preview']==[] and 'duration unavailable' in item['decision_reason']
