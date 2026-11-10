"""Require an administrator, the correct origin, and fresh checks for recovery."""
from flask import Flask
from app.json_recovery_web import create_blueprint
from app.json_scan_control import KEY
from test_json_move_execution import move_case
from test_json_move_recovery import interrupt
import json
import re


def test_review_and_record_move_never_replay_rename_or_arr_write(move_case,monkeypatch):
    store,req,server=interrupt(move_case,monkeypatch,'after_rename')
    monkeypatch.setenv('AUDITOR_WORKER_MODE','json_serialized')
    app=Flask(__name__,template_folder='../app/templates'); app.testing=True
    app.context_processor(lambda:{'viewer':{'admin':True,'name':'Fixture'}})
    values={'STATE_FILE':str(store.path),'RADARR_URL':'http://127.0.0.1:'+str(server.server_port),'RADARR_API_KEY':'synthetic-token'}
    app.register_blueprint(create_blueprint(lambda:True,lambda:values))
    client=app.test_client(); url='/operation-recovery'; headers={'Origin':'http://localhost'}
    before=store.path.read_bytes(); calls=list(server.calls)
    assert client.get(url).status_code == 200 and server.calls == calls
    assert client.post(url,data={'action':'review'},headers={'Origin':'http://outside.invalid'}).status_code == 403
    response=client.post(url,data={'action':'review'},headers=headers)
    assert response.status_code == 200 and store.path.read_bytes() == before
    match=re.search('name="fingerprint" value="([0-9a-f]{64})"',response.text); assert match
    assert 'synthetic-token' not in response.text and str(store.path) not in response.text
    response=client.post(url,data={'action':'record_move','fingerprint':match[1]},headers=headers)
    assert response.status_code == 200
    state=json.loads(store.path.read_bytes()); assert state[KEY]['journal']['kind'] == 'arr_sync'
    assert not any(method == 'PUT' for method,_ in server.calls)
    # Replaying the old consent cannot dispatch an Arr update.
    response=client.post(url,data={'action':'finish_arr_sync','fingerprint':match[1]},headers=headers)
    assert response.status_code == 409 and not any(method == 'PUT' for method,_ in server.calls)


def test_recovery_route_requires_selected_worker_and_admin(monkeypatch):
    app=Flask(__name__); app.register_blueprint(create_blueprint(lambda:False))
    client=app.test_client()
    monkeypatch.delenv('AUDITOR_WORKER_MODE',raising=False)
    assert client.get('/operation-recovery').status_code == 404
    monkeypatch.setenv('AUDITOR_WORKER_MODE','json_serialized')
    assert client.get('/operation-recovery').status_code == 401
