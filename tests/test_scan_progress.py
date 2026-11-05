from concurrent.futures import ThreadPoolExecutor
from threading import Event
from app.scan_progress import observe,emit
from test_json_worker_cycle import cycle_case
from test_json_move_execution import move_case
from test_json_worker_service import service
from app import json_worker_service
import web


def test_sink_is_scoped_allowlisted_and_never_changes_outcome():
    rows=[]
    with observe(rows.append):
        emit('jellyfin',checked=1,total=2,library='TV')
        emit('private path')
        emit('jellyfin',checked=True,total=2)
        emit('jellyfin',checked=3,total=2)
    emit('saving')
    assert len(rows)==1 and rows[0]['checked']==1
    def broken(row):raise RuntimeError('instrumentation failed')
    with observe(broken):emit('saving')


def test_running_progress_is_live_readonly_and_disappears_after_completion(cycle_case,monkeypatch):
    worker=service(cycle_case)
    entered,release=Event(),Event()
    real=worker.execute
    def execute(*args,**kwargs):
        emit('jellyfin',checked=128,total=541,library='Movies')
        entered.set();assert release.wait(10)
        return real(*args,**kwargs)
    worker.execute=execute
    monkeypatch.setenv('AUDITOR_WORKER_MODE','json_serialized')
    monkeypatch.setattr(json_worker_service,'SERVICE',worker)
    monkeypatch.setattr(web,'current_user',lambda:{'admin':True,'name':'Test'})
    monkeypatch.setattr(web,'selected_run_snapshot',lambda fallback:worker.report())
    client=web.app.test_client()
    assert worker.request()['status']=='queued'
    with ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(worker.run_once,trigger='manual')
        assert entered.wait(5)
        try:
            progress=worker.progress_report()
            assert progress['phase']=='jellyfin' and progress['checked']==128
            assert progress['total']==541 and progress['elapsed_seconds']>=0
            response=client.get('/api/run-status')
            assert response.status_code==200 and response.json['progress']['checked']==128
            assert response.headers['Cache-Control']=='no-store'
            assert worker.request()['status']=='busy'
        finally:release.set()
        assert result.result()['result']=='completed'
    assert worker.progress_report() is None
    assert 'progress' not in client.get('/api/run-status').json
    assert service(cycle_case).progress_report() is None


def test_reporter_does_not_cross_threads():
    rows=[]
    with observe(rows.append):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(emit,'saving').result()
    assert rows==[]


def test_failed_worker_clears_live_progress_and_preserves_failure(cycle_case):
    worker=service(cycle_case)
    def fail(*args,**kwargs):
        emit('inventory')
        raise RuntimeError('synthetic failure')
    worker.execute=fail
    assert worker.request()['status']=='queued'
    record=worker.run_once(trigger='manual')
    assert record['result']=='failed'
    assert worker.progress_report() is None
    assert worker.report()['running'] is False
