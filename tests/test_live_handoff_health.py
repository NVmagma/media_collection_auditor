"""Live readiness must distinguish a bounded live worker from preview or unsafe responses."""
import json
from types import SimpleNamespace
import pytest
from scripts import sqlite_preview_service as service

@pytest.mark.parametrize('change',[None,'preview','pending','deletion','worker','authentication'])
def test_live_health_requires_authenticated_one_action_policy(monkeypatch,change):
    common=dict(storage_authority='sqlite',production_activation='scheduled_moves',freshness_verified=False,
        read_only=True,media_actions_authorized=False,execution_mode='scheduled_live_moves',
        worker_mode='daily_moves_one_action',permanent_deletion_authorized=False)
    summary={**common,'pending_operation_present':False};audit={**common,'next_run':'2026-10-30T09:00:00+00:00'}
    if change=='preview':summary['production_activation']='preview_only'
    if change=='pending':summary['pending_operation_present']=True
    if change=='deletion':audit['permanent_deletion_authorized']=True
    if change=='worker':audit['worker_mode']='unbounded'
    ticks=iter([0,0,31]);monkeypatch.setattr(service,'monotonic',lambda:next(ticks))
    monkeypatch.setattr(service,'sleep',lambda value:None)
    calls=[]
    class Connection:
        def __init__(self,address,port,timeout):assert address=='172.17.0.2' and timeout==2
        def request(self,method,route,headers):self.route,self.auth=route,bool(headers);calls.append((route,bool(headers)))
        def getresponse(self):
            status=200 if self.auth or change=='authentication' else 401
            data=summary if self.route.endswith('summary') else audit
            return SimpleNamespace(status=status,read=lambda limit:json.dumps(data).encode())
        def close(self):pass
    monkeypatch.setattr(service.http.client,'HTTPConnection',Connection)
    engine=SimpleNamespace(inspect=lambda identity:{'State':{'Running':True},
        'NetworkSettings':{'Networks':{'bridge':{'IPAddress':'172.17.0.2'}}}})
    args=dict(engine=engine,identity='a'*64,env={'INTEGRATION_API_TOKEN':'synthetic'},live_canary=True)
    if change is None:service.verify_http_health(**args)
    else:
        with pytest.raises(RuntimeError):service.verify_http_health(**args)
    assert calls
