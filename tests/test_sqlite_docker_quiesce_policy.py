"""Strict reduction-only policy tests; never stop/update a real container."""
import base64
import json
import pytest
from app.sqlite_docker_quiesce_policy import authorize_quiesce_request as authorize
from app.sqlite_docker_maintenance_hold import create_disposable_hold, held_disposable_hold

ID='a'*64
OTHER='b'*64


def update(value=None):
    raw=json.dumps(value if value is not None else {'RestartPolicy':{'Name':'no','MaximumRetryCount':0}}).encode()
    return {'RequestMethod':'POST','RequestURI':f'/containers/{ID}/update',
            'RequestHeader':{'Content-Type':'application/json','Content-Length':str(len(raw))},
            'RequestBody':base64.b64encode(raw).decode()}


def test_only_selected_stop_and_restart_disable_can_allow():
    assert authorize(update(),(ID,))['Allow'] is True
    assert authorize({'RequestMethod':'POST','RequestURI':f'/containers/{ID}/stop'},(ID,))['Allow'] is True
    assert authorize(update(),())['Allow'] is False
    assert authorize(update(),(OTHER,))['Allow'] is False


@pytest.mark.parametrize('value', [
    {'RestartPolicy':{'Name':'always','MaximumRetryCount':0}},
    {'RestartPolicy':{'Name':'unless-stopped','MaximumRetryCount':0}},
    {'RestartPolicy':{'Name':'on-failure','MaximumRetryCount':0}},
    {'RestartPolicy':{'Name':'no','MaximumRetryCount':True}},
    {'RestartPolicy':{'Name':'no','MaximumRetryCount':0.0}},
    {'RestartPolicy':{'Name':'no','MaximumRetryCount':0},'Privileged':True},
    {'RestartPolicy':{'Name':'no','MaximumRetryCount':0},'Memory':10},
    {'restartpolicy':{'Name':'no','MaximumRetryCount':0}}, [],None])
def test_restart_enable_and_unrelated_changes_deny(value):
    candidate=update(value) if value is not None else update({'RestartPolicy':None})
    assert authorize(candidate,(ID,))['Allow'] is False


@pytest.mark.parametrize('action', ['start','restart','unpause','exec','kill','attach','archive'])
def test_no_other_control_action_is_permitted(action):
    assert authorize({'RequestMethod':'POST','RequestURI':f'/containers/{ID}/{action}'},(ID,))['Allow'] is False


@pytest.mark.parametrize('change', ['duplicate','base64','framing','content_type','upgrade','short_id','query','version'])
def test_ambiguous_or_unknown_update_forms_deny(change):
    request=update()
    if change=='duplicate': request['RequestBody']=base64.b64encode(b'{"RestartPolicy":{},"RestartPolicy":{"Name":"no","MaximumRetryCount":0}}').decode()
    elif change=='base64': request['RequestBody']='not base64'
    elif change=='framing': request['RequestHeader']['Content-Length']='999'
    elif change=='content_type': request['RequestHeader']['Content-Type']='application/octet-stream'
    elif change=='upgrade': request['RequestHeader']['Upgrade']='h2c'
    elif change=='short_id': request['RequestURI']='/containers/short/update'
    elif change=='query': request['RequestURI']+='?anything=1'
    else: request['RequestURI']='/v1.54'+request['RequestURI']
    assert authorize(request,(ID,))['Allow'] is False


def test_scope_is_durable_and_live_replacement_blocks(tmp_path):
    root=tmp_path/'fixture';root.mkdir()
    (root/'.disposable_authorization').write_bytes(b'DISPOSABLE ONLY\n')
    create_disposable_hold(root,container_ids=(ID,))
    with held_disposable_hold(root) as verify:
        assert verify.quiesce_container_ids==frozenset((ID,))
        verify()
    with pytest.raises(RuntimeError):
        with held_disposable_hold(root) as verify:
            (root/'quiesce.json').write_text(json.dumps([OTHER])+'\n')
            verify()


@pytest.mark.parametrize('scope', [('name',),('abc123',),(ID,ID),(True,),[ID]*101])
def test_invalid_scope_cannot_create_an_authorization_hold(tmp_path, scope):
    root=tmp_path/'fixture';root.mkdir()
    (root/'.disposable_authorization').write_bytes(b'DISPOSABLE ONLY\n')
    with pytest.raises(ValueError): create_disposable_hold(root,container_ids=scope)
    assert sorted(p.name for p in root.iterdir())==['.disposable_authorization']


def test_duplicate_go_json_fields_rejected_even_with_correct_length():
    raw=b'{"RestartPolicy":{"Name":"always","Name":"no","MaximumRetryCount":0}}'
    request=update()
    request['RequestBody']=base64.b64encode(raw).decode()
    request['RequestHeader']['Content-Length']=str(len(raw))
    assert authorize(request,(ID,))['Allow'] is False
