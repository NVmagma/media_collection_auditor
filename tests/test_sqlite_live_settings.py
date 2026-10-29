"""Real live bindings, advanced clocks and shared crash-safe settings transaction."""
import hashlib,json,os,signal
import pytest
from test_sqlite_live_binding import prepared
from app import sqlite_live_binding as live
from app import sqlite_live_settings as settings
from app import sqlite_preview_settings_apply as transaction
from app.sqlite_preview_settings import PENDING
from app.state_store import GuardedSQLiteStateStore


def request(prepared,**changes):
    _,_,_,config,values=prepared
    current=json.loads(config.read_bytes());current.update(changes)
    return settings.request_settings(config_path=config,updated=current,environment=values,include_digest=True)['request_sha256']


def test_live_settings_preserve_advanced_state_source_unknowns_and_claims(prepared):
    _,source,control,config,values=prepared
    live.create_live_binding(settings=values)
    store=GuardedSQLiteStateStore(control/'state.db');state,revision=store.load_with_revision()
    state['custom-extension']={'retain':['clock','queue']};store.save_if_revision(state,revision)
    claim=control/'.sqlite_scheduled_slots';claim.mkdir(mode=0o700);(claim/'existing.json').write_text('retained')
    before=store.load_with_revision();raw=source.read_bytes();database=(control/'state.db').read_bytes()
    digest=request(prepared,HOLDING_DAYS='12')
    result=settings.apply_requested_settings(settings=values,request_sha256=digest)
    assert result['tracking_unchanged'] and not result['media_actions_authorized']
    assert live.validate_live_binding(settings=values,for_execution=True)['HOLDING_DAYS']=='12'
    assert store.load_with_revision()==before and source.read_bytes()==raw
    assert (control/'state.db').read_bytes()==database and (claim/'existing.json').read_text()=='retained'
    assert not (config.parent/PENDING).exists()


@pytest.mark.parametrize('key,value',[('MAX_ACTIONS_PER_RUN','2'),('ALLOW_PERMANENT_DELETE','true'),
    ('ALLOW_FILESYSTEM_DELETE','true'),('ALLOW_CROSS_FILESYSTEM_MOVES','true'),('ENABLE_SEASON_PRUNING','true'),
    ('MEDIA_PATH','/different'),('SQLITE_DAILY_RUN_TIMEZONE','Europe/London'),('DRY_RUN','true')])
def test_live_canary_controls_cannot_change_through_settings(prepared,key,value):
    _,_,control,config,values=prepared;live.create_live_binding(settings=values)
    raw=config.read_bytes();binding=(control/live.BINDING).read_bytes()
    with pytest.raises((ValueError,RuntimeError)):request(prepared,**{key:value})
    assert config.read_bytes()==raw and (control/live.BINDING).read_bytes()==binding
    assert not (control/live.SETTINGS_MARKER).exists()


@pytest.mark.parametrize('phase',['after_intent','after_config','after_binding','after_complete'])
def test_interruption_pauses_execution_and_explicit_restore_keeps_latest_tracking(prepared,monkeypatch,phase):
    _,_,control,config,values=prepared;live.create_live_binding(settings=values)
    store=GuardedSQLiteStateStore(control/'state.db');state,revision=store.load_with_revision()
    state['custom-latest']=True;store.save_if_revision(state,revision)
    before=store.load_with_revision();old=config.read_bytes();digest=request(prepared,HOLDING_DAYS='15')
    def fail(where):
        if where==phase:raise RuntimeError('synthetic interruption')
    monkeypatch.setattr(transaction,'_boundary',fail)
    with pytest.raises(RuntimeError):settings.apply_requested_settings(settings=values,request_sha256=digest)
    with pytest.raises(RuntimeError):live.validate_live_binding(settings=values,for_execution=True)
    assert store.load_with_revision()==before
    monkeypatch.setattr(transaction,'_boundary',lambda where:None)
    assert settings.restore_previous_settings(settings=values,request_sha256=digest)['tracking_unchanged']
    assert config.read_bytes()==old and store.load_with_revision()==before
    assert live.validate_live_binding(settings=values,for_execution=True)


def test_actual_controller_sigkill_after_config_requires_explicit_restore(prepared,monkeypatch):
    _,_,control,_,values=prepared;live.create_live_binding(settings=values)
    digest=request(prepared,HOLDING_DAYS='19')
    import subprocess,sys
    code="""
import json,os,signal,sys
from app import sqlite_release_profile as build
build.PROFILE='scheduled-live-moves-v1';build.SOURCE_REVISION='b'*40
from app import sqlite_preview_settings_apply as transaction
from app.sqlite_live_settings import apply_requested_settings
values=json.load(sys.stdin)
def die(where):
    if where=='after_config':os.kill(os.getpid(),signal.SIGKILL)
transaction._boundary=die
apply_requested_settings(settings=values['settings'],request_sha256=values['digest'])
"""
    result=subprocess.run([sys.executable,'-B','-c',code],input=json.dumps({'settings':values,'digest':digest}),
        text=True,capture_output=True,timeout=20)
    assert result.returncode==-signal.SIGKILL
    with pytest.raises(RuntimeError):live.validate_live_binding(settings=values,for_execution=True)
    settings.restore_previous_settings(settings=values,request_sha256=digest)
    assert live.validate_live_binding(settings=values,for_execution=True)
