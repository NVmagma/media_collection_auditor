"""Send optional JSON failure alerts without private details or duplicate messages."""
from unittest.mock import Mock
from app import operational_notifications as alerts
from test_json_worker_service import service,cycle_case
from test_json_move_execution import move_case


def test_json_failures_deduplicate_and_success_rearms(cycle_case,monkeypatch):
    sent=[]
    notifier=alerts.OperationalNotifications(deliver=lambda *args:sent.append(args) or True)
    monkeypatch.setattr(alerts,'NOTIFICATIONS',notifier)
    cycle_case[1].update(NOTIFY_OPERATIONAL_FAILURES='true',NOTIFY_WEBHOOK_URL='https://example.invalid/hook')
    worker=service(cycle_case)
    worker.execute=lambda *args,**kwargs:{'result':'failed','pending_operation_present':False}
    for _ in range(2):
        assert worker.request()['status']=='queued'
        worker.run_once(trigger='manual')
    assert len(sent)==1 and 'private' not in str(sent)
    worker.execute=lambda *args,**kwargs:{'result':'completed','completed_moves':[]}
    worker.request();worker.run_once(trigger='manual')
    worker.execute=lambda *args,**kwargs:{'result':'failed'}
    worker.request();worker.run_once(trigger='manual')
    assert len(sent)==2
