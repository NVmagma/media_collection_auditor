from copy import deepcopy
import os
import pytest
from scripts import sqlite_preview_service_fixture as fixtures
from scripts import sqlite_preview_cutover_fixture as cutover
from scripts.sqlite_preview_service import Journal,preview_payload
from scripts.unraid_update_candidate_handoff import handoff


@pytest.fixture
def ready():
    case=cutover.PreviewCutoverFixtureTests();case.setUp()
    try:
        _,_,env,_=case.render();old=deepcopy(case.old[0]);engine=fixtures.Engine(old)
        payload=preview_payload(captured=old,image=engine.selected_image,env=env,
            control_host='/new/control',reference=fixtures.REFERENCE,request_id=fixtures.REQUEST_ID)
        parent=os.open(case.root,os.O_DIRECTORY|os.O_RDONLY)
        installed=[];checks=[]
        def precheck():checks.append(engine.inspect(old['Id'])['State']['Running'])
        options=dict(engine=engine,journal=Journal(parent),captured=old,payload=payload,image_id=cutover.NEW,
            precheck=precheck,health=lambda identity:None,install=lambda:installed.append(True))
        try:yield options,installed,checks
        finally:os.close(parent)
    finally:case.doCleanups()


def test_complete_handoff_checks_state_online_and_offline_and_retains_old(ready):
    options,installed,checks=ready
    assert handoff(**options)['status']=='candidate_preview_update_complete'
    assert checks==[True,False] and installed==[True]
    assert [value[0] for value in options['engine'].calls]==['stop','rename','create','start']
    assert not options['engine'].inspect(options['captured']['Id'])['State']['Running']


@pytest.mark.parametrize('operation',['stop','rename','create','start'])
def test_lost_ack_never_retries_or_restores(ready,operation):
    options,installed,_=ready;options['engine'].lose_ack=operation
    with pytest.raises(TimeoutError):handoff(**options)
    before=list(options['engine'].calls)
    with pytest.raises((RuntimeError,FileExistsError)):handoff(**options)
    assert options['engine'].calls==before and installed==[]


def test_changed_tracking_after_stop_blocks_before_archive(ready):
    options,installed,_=ready
    def precheck():
        if not options['engine'].inspect(options['captured']['Id'])['State']['Running']:raise RuntimeError('Changed state')
    options['precheck']=precheck
    with pytest.raises(RuntimeError):handoff(**options)
    assert [item[0] for item in options['engine'].calls]==['stop'] and installed==[]


def test_failed_health_never_installs_template(ready):
    options,installed,_=ready
    def fail(identity):raise RuntimeError('Health failed')
    options['health']=fail
    with pytest.raises(RuntimeError):handoff(**options)
    assert installed==[]


def test_explicit_recovery_retains_replacement_and_starts_original(ready):
    from scripts.unraid_update_candidate_handoff import recover
    options,_,_=ready;result=handoff(**options)
    common={key:value for key,value in options.items() if key not in ('install','precheck','journal')}
    restored=[]
    report=recover(**common,journal=Journal(options['journal'].parent,'recovery'),new_id=result['container_id'],
        precheck=lambda:None,restore_template=lambda:restored.append(True))
    assert report['status']=='candidate_update_original_recovered' and restored==[True]
    assert options['engine'].inspect(options['captured']['Id'])['State']['Running']
    assert not options['engine'].inspect(result['container_id'])['State']['Running']


def test_recovery_blocks_changed_data_without_stopping_replacement(ready):
    from scripts.unraid_update_candidate_handoff import recover
    options,_,_=ready;result=handoff(**options);before=list(options['engine'].calls)
    common={key:value for key,value in options.items() if key not in ('install','precheck','journal')}
    def fail():raise RuntimeError('Tracking changed')
    with pytest.raises(RuntimeError):
        recover(**common,journal=Journal(options['journal'].parent,'recovery'),new_id=result['container_id'],
            precheck=fail,restore_template=lambda:None)
    assert options['engine'].calls==before
