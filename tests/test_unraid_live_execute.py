"""Live service transaction uses real private review inputs and fake engine actions."""
from copy import deepcopy
import hashlib,os
from unittest.mock import patch
import pytest
from app import sqlite_release_profile as build
from app.sqlite_live_binding import PROFILE
from app.state_store import GuardedSQLiteStateStore
from tests.test_unraid_live_review import case,run,identity
from scripts.sqlite_preview_service_fixture import Engine
from scripts import unraid_live_execute as execute

@pytest.fixture
def selected(case):
    run(case)
    folder=case.root/'templates';folder.mkdir(mode=0o700)
    (folder/'current.xml').write_bytes(case.template)
    engine=Engine(case.current);engine.containers={case.current['Id']:deepcopy(case.current)}
    engine.selected_image=deepcopy(case.image)
    def created(item):
        item['Image']=case.image['Id']
        item['HostConfig'].update(CapDrop=['ALL'],CapAdd=['DAC_OVERRIDE'],SecurityOpt=['no-new-privileges'])
    engine.on_create=created
    args=dict(engine=engine,review=case.output,review_identity=identity(case.output),
        review_fingerprint=hashlib.sha256((case.output/'review-complete.json').read_bytes()).hexdigest(),
        backup=case.backup,backup_identity=identity(case.backup),backup_fingerprint=case.fingerprint,
        logs=case.logs,control=case.control,old_logs=case.root,old_control=case.old_control,templates=folder,
        shared_media=case.shared,native_media=case.native)
    with patch.object(build,'PROFILE',PROFILE):yield case,args,engine


def test_preflight_never_controls_services(selected):
    _,args,engine=selected
    assert execute.run_selected(execute.SelectedLive(**args),action='check',parent=None)['status']=='live_handoff_preflight_verified'
    assert engine.calls==[]


def deploy(selected,monkeypatch):
    case,args,engine=selected
    monkeypatch.setattr(execute,'verify_http_health',lambda **kwargs:None)
    update=execute.SelectedLive(**args);fd=os.open(case.output,os.O_RDONLY|os.O_DIRECTORY)
    try:return execute.run_selected(update,action='deploy',parent=fd)
    finally:os.close(fd)


def test_live_handoff_and_unchanged_explicit_recovery(selected,monkeypatch):
    case,args,engine=selected
    assert deploy(selected,monkeypatch)['initial_maximum_actions']==1
    update=execute.SelectedLive(**args);fd=os.open(case.output,os.O_RDONLY|os.O_DIRECTORY)
    try:result=execute.run_selected(update,action='recover',parent=fd)
    finally:os.close(fd)
    assert result['status']=='unchanged_live_canary_preview_recovered'
    assert engine.inspect(case.current['Id'])['State']['Running']


@pytest.mark.parametrize('operation',['stop','rename','create','start'])
def test_lost_ack_never_replays(selected,monkeypatch,operation):
    _,args,engine=selected;engine.lose_ack=operation
    with pytest.raises(TimeoutError):deploy(selected,monkeypatch)
    before=list(engine.calls)
    with pytest.raises((RuntimeError,FileExistsError)):deploy(selected,monkeypatch)
    assert engine.calls==before


def test_advanced_tracking_blocks_stale_recovery_before_service_actions(selected,monkeypatch):
    case,args,engine=selected;deploy(selected,monkeypatch)
    store=GuardedSQLiteStateStore(case.control/'release/state.db')
    state,revision=store.load_with_revision();state['extension']='latest';store.save_if_revision(state,revision)
    before=list(engine.calls);fd=os.open(case.output,os.O_RDONLY|os.O_DIRECTORY)
    try:
        with pytest.raises(RuntimeError):execute.run_selected(execute.SelectedLive(**args),action='recover',parent=fd)
    finally:os.close(fd)
    assert engine.calls==before


def test_unapproved_capabilities_stop_before_start_or_template(selected,monkeypatch):
    _,args,engine=selected
    def wrong(item):
        item['Image']=engine.selected_image['Id'];item['HostConfig']['CapAdd']=['SYS_ADMIN']
    engine.on_create=wrong
    with pytest.raises(RuntimeError):deploy(selected,monkeypatch)
    assert 'start' not in [call[0] for call in engine.calls]


def test_pending_intent_blocks_recovery_without_stopping_live(selected,monkeypatch):
    from app.sqlite_operation_coordinator import INTENTS_KEY
    case,args,engine=selected;deploy(selected,monkeypatch)
    store=GuardedSQLiteStateStore(case.control/'release/state.db')
    state,revision=store.load_with_revision();state[INTENTS_KEY]={'uncertain':'retained'}
    store.save_if_revision(state,revision)
    before=list(engine.calls);fd=os.open(case.output,os.O_RDONLY|os.O_DIRECTORY)
    try:
        with pytest.raises(RuntimeError):execute.run_selected(execute.SelectedLive(**args),action='recover',parent=fd)
    finally:os.close(fd)
    assert engine.calls==before
