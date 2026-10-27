"""Stopped-preview handoff never retries, removes or restarts old containers."""
from copy import deepcopy
import os
import pytest
from scripts.sqlite_preview_service_fixture import Engine,NEW_ID,REQUEST_ID,REFERENCE
from scripts.sqlite_preview_cutover_fixture import PreviewCutoverFixtureTests,IDENTIFIER,NEW
from scripts.sqlite_preview_service import Journal,preview_payload,NAME
from scripts.unraid_preview_recovery_start import start_selected


@pytest.fixture
def recovery():
    case=PreviewCutoverFixtureTests();case.setUp()
    _,_,env,_=case.render()
    old=deepcopy(case.old[0]);old['State']['Running']=False
    engine=Engine(old)
    payload=preview_payload(captured=old,image=engine.selected_image,env=env,
        control_host='/new-private/control',reference=REFERENCE,request_id=REQUEST_ID)
    parent=os.open(case.root,os.O_RDONLY|os.O_DIRECTORY)
    installed=[]
    def run(**changes):
        options=dict(engine=engine,journal=Journal(parent,'recovery'),captured=old,
            selection={'attempt':REQUEST_ID,'image_id':NEW},payload=payload,precheck=lambda:None,
            health=lambda identity:None,install=lambda:installed.append(True))
        options.update(changes)
        return start_selected(**options)
    try:yield engine,run,installed
    finally:os.close(parent);case.doCleanups()


def test_stopped_original_retained_and_new_preview_started_once(recovery):
    engine,run,installed=recovery
    assert run()['status']=='tv_preview_recovery_complete'
    assert engine.inspect(IDENTIFIER)['State']['Running'] is False
    assert engine.inspect(NEW_ID)['State']['Running'] is True
    assert installed==[True]
    assert [x[0] for x in engine.calls]==['rename','create','start']


@pytest.mark.parametrize('operation',['rename','create','start'])
def test_lost_ack_never_retries_or_restarts_original(recovery,operation):
    engine,run,installed=recovery;engine.lose_ack=operation
    with pytest.raises(TimeoutError):run()
    before=list(engine.calls)
    with pytest.raises((RuntimeError,FileExistsError)):run()
    assert engine.calls==before and installed==[]
    assert not engine.inspect(IDENTIFIER)['State']['Running']


def test_failed_precheck_has_no_service_effect(recovery):
    engine,run,installed=recovery
    def fail():raise RuntimeError('private detail')
    with pytest.raises(RuntimeError):run(precheck=fail)
    assert engine.calls==[] and installed==[]


def test_failed_health_never_installs_template(recovery):
    engine,run,installed=recovery
    def fail(identity):raise RuntimeError('unhealthy')
    with pytest.raises(RuntimeError):run(health=fail)
    assert installed==[] and not engine.inspect(IDENTIFIER)['State']['Running']
