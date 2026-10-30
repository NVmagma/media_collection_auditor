"""Reviewed live upgrade refuses stale tracking and daily-claim replay."""
from copy import deepcopy
import hashlib
import os

import pytest
from app.state_store import GuardedSQLiteStateStore
from scripts import unraid_live_execute as execute
from scripts.sqlite_preview_service_fixture import Engine
from test_unraid_live_update_review import update_case, run, identity, case


@pytest.fixture
def selected(update_case):
    case=update_case;run(case)
    folder=case.root/'live-update-templates';folder.mkdir(mode=0o700)
    (folder/'current.xml').write_bytes(case.template)
    engine=Engine(case.current);engine.containers={case.current['Id']:deepcopy(case.current)}
    engine.selected_image=deepcopy(case.image)
    def created(item):
        item['Image']=case.image['Id']
        item['HostConfig'].update(CapDrop=['ALL'],CapAdd=['CAP_DAC_OVERRIDE'],SecurityOpt=['no-new-privileges'])
    engine.on_create=created
    args=dict(engine=engine,review=case.output,review_identity=identity(case.output),
        review_fingerprint=hashlib.sha256((case.output/'review-complete.json').read_bytes()).hexdigest(),
        backup=case.backup,backup_identity=identity(case.backup),backup_fingerprint=case.fingerprint,
        logs=case.logs,control=case.control,old_logs=case.old_logs,old_control=case.old_control,
        templates=folder,shared_media=case.native,native_media=case.native)
    return case,args,engine


def action(selected,monkeypatch,kind):
    case,args,_=selected
    monkeypatch.setattr(execute,'verify_http_health',lambda **kwargs:None)
    update=execute.SelectedLiveUpdate(**args)
    if kind=='check':return execute.run_selected(update,action=kind,parent=None)
    fd=os.open(case.output,os.O_RDONLY|os.O_DIRECTORY)
    try:return execute.run_selected(update,action=kind,parent=fd)
    finally:os.close(fd)


def test_live_update_preflight_has_no_service_actions(selected,monkeypatch):
    _,_,engine=selected
    assert action(selected,monkeypatch,'check')['status']=='live_handoff_preflight_verified'
    assert engine.calls==[]


def test_live_update_and_explicit_unchanged_recovery(selected,monkeypatch):
    case,_,engine=selected
    assert action(selected,monkeypatch,'deploy')['media_actions_authorized']
    assert action(selected,monkeypatch,'recover')['status']=='unchanged_live_previous_recovered'
    assert engine.inspect(case.current['Id'])['State']['Running']
    assert (case.old_control/'release/.sqlite_scheduled_slots'/('1'*64+'.json')).exists()


@pytest.mark.parametrize('kind',['advanced','pending','new_claim','claim_removed'])
def test_latest_candidate_state_or_budget_blocks_stale_recovery(selected,monkeypatch,kind):
    from app.sqlite_operation_coordinator import INTENTS_KEY
    case,_,engine=selected;action(selected,monkeypatch,'deploy')
    if kind in ('advanced','pending'):
        store=GuardedSQLiteStateStore(case.control/'release/state.db');state,revision=store.load_with_revision()
        state[INTENTS_KEY if kind=='pending' else 'new-extension']={'retained':True}
        store.save_if_revision(state,revision)
    elif kind=='new_claim':
        path=case.control/'release/.sqlite_scheduled_slots'/('4'*64+'.json')
        path.write_bytes(b'');path.chmod(0o600)
    else:(case.control/'release/.sqlite_scheduled_slots'/('1'*64+'.json')).unlink()
    before=list(engine.calls)
    with pytest.raises(RuntimeError):action(selected,monkeypatch,'recover')
    assert engine.calls==before


def test_claim_created_during_stop_blocks_before_archive_or_create(selected,monkeypatch):
    case,_,engine=selected;original=engine.stop
    def stop(identity):
        original(identity)
        path=case.old_control/'release/.sqlite_scheduled_slots'/('5'*64+'.json')
        path.write_bytes(b'');path.chmod(0o600)
    engine.stop=stop
    with pytest.raises(RuntimeError):action(selected,monkeypatch,'deploy')
    assert [call[0] for call in engine.calls]==['stop']
    assert not engine.inspect(case.current['Id'])['State']['Running']


@pytest.mark.parametrize('operation',['stop','rename','create','start'])
def test_uncertain_service_action_is_never_replayed(selected,monkeypatch,operation):
    _,_,engine=selected;engine.lose_ack=operation
    with pytest.raises(TimeoutError):action(selected,monkeypatch,'deploy')
    before=list(engine.calls)
    with pytest.raises((RuntimeError,FileExistsError)):action(selected,monkeypatch,'deploy')
    assert engine.calls==before
