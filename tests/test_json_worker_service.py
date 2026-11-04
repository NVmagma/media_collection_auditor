"""Serialization, rolling cooldown, daily DST handling and retained activity."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import json
from threading import Event

import pytest
from app.json_worker_service import JSONWorkerService,next_daily
from app.json_scan_control import KEY,scan_attempt
from test_json_worker_cycle import cycle_case,collect,preview
from test_json_move_execution import move_case
from app.json_worker_cycle import run_cycle

NOW=datetime(2026,1,20,12,tzinfo=timezone.utc)


def service(case,**kwargs):
    store,values,_,_,services=case; values['STATE_FILE']=str(store.path)
    execute=lambda store,**args:run_cycle(store,services=services(args['settings']),collect=collect,preview=preview,**args)
    return JSONWorkerService(clock=lambda:NOW,execute=execute,load_settings=lambda:values,**kwargs)


def test_manual_and_scheduled_share_persisted_hourly_gate(cycle_case):
    worker=service(cycle_case)
    assert worker.request()['status'] == 'queued'
    assert worker.request()['status'] == 'busy'
    record=worker.run_once(trigger='manual')
    assert record['result'] == 'completed' and record['moves_completed'] == 2
    assert worker.request()['status'] == 'cooldown'
    # A new process coordinator sees the same durable start, not a fresh budget.
    restarted=service(cycle_case)
    assert restarted.request()['status'] == 'cooldown'
    assert not restarted.report()['execution_blocked']


def test_running_cycle_rejects_another_request_and_status_remains_available(cycle_case):
    worker=service(cycle_case); real=worker.execute
    entered,release=Event(),Event()
    def slow(*args,**kwargs):
        entered.set(); assert release.wait(10); return real(*args,**kwargs)
    worker.execute=slow; assert worker.request()['status'] == 'queued'
    with ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(worker.run_once,trigger='manual')
        assert entered.wait(5)
        try:
            assert worker.report()['running'] and worker.request()['status'] == 'busy'
            with pytest.raises(RuntimeError): worker.run_once(trigger='scheduled')
        finally: release.set()
        assert result.result()['result'] == 'completed'


def test_history_survives_coordinator_restart_without_fabricating_new_completion(cycle_case):
    saved=[]
    worker=service(cycle_case,record=saved.append,read_records=lambda limit:list(reversed(saved[-limit:])))
    worker.request(); worker.run_once(trigger='manual')
    restarted=service(cycle_case,read_records=lambda limit:list(reversed(saved[-limit:])))
    assert restarted.history()[0]['moves_completed'] == 2
    report=restarted.report()
    assert report['history_persistent'] and report['last_result'] == 'completed'
    assert not report['running'] and len(saved) == 1
    assert len(saved[0]['json_decisions']) == 2


def test_pending_operation_blocks_restart_request_without_replay(cycle_case):
    store,values,*_=cycle_case
    with scan_attempt(store,now=NOW,trigger='manual') as attempt:
        attempt.record_intent(kind='arr_sync',library='TV',title='Show',details={'synthetic':True})
    worker=service(cycle_case); worker.clock=lambda:NOW+timedelta(hours=2)
    before=store.path.read_bytes()
    assert worker.request()['status'] == 'review_required'
    assert worker.report()['execution_blocked']
    assert store.path.read_bytes() == before


def test_daily_startup_waits_for_future_slot_and_spring_gap_is_skipped():
    settings={'DAILY_RUN_TIME':'02:00','TZ':'America/Los_Angeles'}
    assert next_daily(settings,datetime(2026,1,20,11,tzinfo=timezone.utc)) == datetime(2026,1,21,10,tzinfo=timezone.utc)
    settings['DAILY_RUN_TIME']='02:30'
    # March 8's 02:30 does not exist, so there is no surprise shifted run.
    assert next_daily(settings,datetime(2026,3,8,8,tzinfo=timezone.utc)) == datetime(2026,3,9,9,30,tzinfo=timezone.utc)


def test_fall_back_has_one_daily_slot_and_invalid_time_is_refused():
    values={'DAILY_RUN_TIME':'01:30','DAILY_RUN_TIMEZONE':'America/Los_Angeles'}
    first=datetime(2026,11,1,8,30,tzinfo=timezone.utc)
    assert next_daily(values,first-timedelta(seconds=1)) == first
    assert next_daily(values,first) == datetime(2026,11,2,9,30,tzinfo=timezone.utc)
    with pytest.raises(ValueError): next_daily({'DAILY_RUN_TIME':'25:00'},NOW)


@pytest.mark.parametrize('key,value',[('DRY_RUN','true'),('MAX_ACTIONS_PER_RUN','10'),('ENABLE_TV','false')])
def test_changed_queued_settings_never_expand_or_change_a_confirmed_attempt(cycle_case,key,value):
    store,values,_,server,_=cycle_case; worker=service(cycle_case)
    before=store.path.read_bytes()
    assert worker.request()['status']=='queued'
    values[key]=value
    record=worker.run_once(trigger='manual')
    assert record['result']=='failed' and record['moves_completed'] is None
    assert store.path.read_bytes()==before and not server.calls
    assert not worker.report()['queued']


def test_preview_request_cannot_queue_live_settings(cycle_case):
    worker=service(cycle_case)
    assert worker.request(expected_dry_run=True)['status']=='settings_changed'
    assert not worker.report()['queued']
