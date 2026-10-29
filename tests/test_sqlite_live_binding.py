from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys
import pytest
from app import sqlite_live_binding as live,sqlite_release_profile as build
from app.sqlite_live_integrity import KEY
from app.sqlite_live_policy import DISABLED
from app.state_store import GuardedSQLiteStateStore
from app.sqlite_operation_coordinator import INTENTS_KEY
from scripts.sqlite_preview_release_fixture import prepare_case

pytestmark=pytest.mark.skipif(sys.platform!='linux',reason='Descriptor-bound live preparation')


@pytest.fixture
def prepared(monkeypatch):
    case,source,control,saved,values=prepare_case()
    values.update(DRY_RUN='false',MAX_ACTIONS_PER_RUN='1',**{key:'false' for key in DISABLED})
    monkeypatch.setattr(build,'PROFILE',live.PROFILE);monkeypatch.setattr(build,'SOURCE_REVISION','b'*40)
    try:yield case,source,control,saved,values
    finally:case.doCleanups()


def test_new_binding_retains_source_and_clocks_and_allows_guarded_revisions(prepared):
    _,source,control,_,values=prepared;store=GuardedSQLiteStateStore(control/'state.db')
    before=store.load_with_revision();original=source.read_bytes()
    assert live.create_live_binding(settings=values)['production_activation']=='disabled'
    assert store.load_with_revision()==before
    assert live.validate_live_binding(settings=values,for_execution=True)['DRY_RUN']=='false'
    state,revision=before;state['custom-extension']={'preserve':True}
    store.save_if_revision(state,revision)
    assert live.validate_live_binding(settings=values,for_execution=True)['DRY_RUN']=='false'
    assert source.read_bytes()==original
    assert 'synthetic-token' not in (control/live.BINDING).read_text()


@pytest.mark.parametrize('profile',['sealed','scheduled-preview-v1'])
def test_other_images_cannot_prepare_or_validate_live_binding(prepared,monkeypatch,profile):
    _,_,control,_,values=prepared;before={p.name:p.read_bytes() for p in control.iterdir() if p.is_file()}
    monkeypatch.setattr(build,'PROFILE',profile)
    with pytest.raises(RuntimeError):live.create_live_binding(settings=values)
    with pytest.raises(RuntimeError):live.validate_live_binding(settings=values)
    assert {p.name:p.read_bytes() for p in control.iterdir() if p.is_file()}==before


@pytest.mark.parametrize('change',['database','settings','roots','source','marker','integrity'])
def test_changed_inputs_never_validate_as_live(prepared,change):
    _,source,control,saved,values=prepared;live.create_live_binding(settings=values)
    database=control/'state.db'
    if change=='database':
        raw=database.read_bytes();database.rename(control/'retained.db');database.write_bytes(raw)
    elif change=='settings':saved.write_text('{"HOLDING_DAYS":"99"}')
    elif change=='roots':
        root=Path(values['RADARR_TRANSIENT_PATH']);root.rename(root.with_name('retained-stage'));root.mkdir()
    elif change=='source':source.write_bytes(source.read_bytes()+b' ')
    elif change=='marker':(control/live.SETTINGS_MARKER).write_text('{}')
    else:
        with closing(sqlite3.connect(database)) as connection:
            connection.execute('DELETE FROM metadata WHERE key=?',(KEY,));connection.commit()
    with pytest.raises((RuntimeError,ValueError,OSError)):live.validate_live_binding(settings=values,for_execution=True)


def test_pending_intent_blocks_execution_but_read_only_binding_remains_observable(prepared):
    _,_,control,_,values=prepared;live.create_live_binding(settings=values)
    store=GuardedSQLiteStateStore(control/'state.db');state,revision=store.load_with_revision()
    state[INTENTS_KEY]={'fixture':'unresolved'};store.save_if_revision(state,revision)
    assert live.validate_live_binding(settings=values)['AUDITOR_STATE_BACKEND']=='sqlite'
    with pytest.raises(RuntimeError):live.validate_live_binding(settings=values,for_execution=True)
    assert store.load_with_revision()[0][INTENTS_KEY]=={'fixture':'unresolved'}


def test_interruption_before_final_binding_retains_request_without_replay(prepared,monkeypatch):
    _,_,control,_,values=prepared;original=live._write_private
    def fail(parent,name,raw):
        if name==live.BINDING:raise RuntimeError('fixture interruption')
        return original(parent,name,raw)
    monkeypatch.setattr(live,'_write_private',fail)
    with pytest.raises(RuntimeError):live.create_live_binding(settings=values)
    assert (control/live.PREPARE).exists() and not (control/live.BINDING).exists()
    with pytest.raises((RuntimeError,OSError)):live.validate_live_binding(settings=values,for_execution=True)
    monkeypatch.setattr(live,'_write_private',original)
    with pytest.raises(FileExistsError):live.create_live_binding(settings=values)


def test_existing_preview_binding_is_never_rebound_in_place(prepared):
    _,_,control,_,values=prepared;(control/'preview-release.json').write_text('{}')
    before=(control/'state.db').read_bytes()
    with pytest.raises(RuntimeError):live.create_live_binding(settings=values)
    assert (control/'state.db').read_bytes()==before
    assert not (control/live.PREPARE).exists()


def test_actual_capped_move_keeps_live_binding_valid_after_clock_commit(prepared):
    from datetime import timedelta
    from app.sqlite_scheduled_production import _configured_cycle_step
    from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle
    from scripts.sqlite_scheduled_configured_slot_fixture import NOW
    case,source,control,_,values=prepared;original=source.read_bytes()
    live.create_live_binding(settings=values);cycle=ScheduledWorkerCycle();slot=case.fixture.slot
    _configured_cycle_step(cycle=cycle,settings=values,now=slot-timedelta(hours=1),clock=lambda:NOW)
    result=_configured_cycle_step(cycle=cycle,settings=values,now=slot,clock=lambda:NOW)
    assert len(result.outcome['completed'])==1
    assert GuardedSQLiteStateStore(control/'state.db').load_with_revision()[1]==3
    assert live.validate_live_binding(settings=values,for_execution=True)['DRY_RUN']=='false'
    assert source.read_bytes()==original


def test_uncertain_actual_rename_retains_integrity_and_blocks_execution(prepared,monkeypatch):
    from datetime import timedelta
    from app.sqlite_scheduled_production import _configured_cycle_step
    from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle
    from scripts.sqlite_scheduled_configured_slot_fixture import NOW
    import app.sqlite_scheduled_routed_batch as batch
    case,_,control,_,values=prepared;live.create_live_binding(settings=values)
    original=batch.rename_directory_noreplace_at
    def uncertain(*args):original(*args);raise RuntimeError('fixture lost acknowledgement')
    monkeypatch.setattr(batch,'rename_directory_noreplace_at',uncertain)
    cycle=ScheduledWorkerCycle();slot=case.fixture.slot
    _configured_cycle_step(cycle=cycle,settings=values,now=slot-timedelta(hours=1),clock=lambda:NOW)
    with pytest.raises(RuntimeError,match='SQLite live release binding unavailable'):
        _configured_cycle_step(cycle=cycle,settings=values,now=slot,clock=lambda:NOW)
    assert INTENTS_KEY in GuardedSQLiteStateStore(control/'state.db').load_with_revision()[0]
    assert live.validate_live_binding(settings=values)['AUDITOR_STATE_BACKEND']=='sqlite'
    calls=len(case.server.calls)
    with pytest.raises(RuntimeError):live.validate_live_binding(settings=values,for_execution=True)
    assert len(case.server.calls)==calls


def test_public_read_gate_observes_pending_intent_without_execution_authority(prepared):
    from app.sqlite_backend_gate import require_sqlite_read_authority, require_sqlite_production_activation
    _,_,control,_,values=prepared
    live.create_live_binding(settings=values)
    store=GuardedSQLiteStateStore(control/'state.db')
    state,revision=store.load_with_revision()
    state[INTENTS_KEY]={'fixture':'unresolved'}
    store.save_if_revision(state,revision)
    before=store.load_with_revision()
    assert require_sqlite_read_authority(settings=values)['DRY_RUN']=='false'
    with pytest.raises(RuntimeError,match='SQLite live release binding unavailable'):
        require_sqlite_production_activation(settings=values)
    assert store.load_with_revision()==before


def test_public_live_gate_redacts_binding_failure(prepared,monkeypatch):
    from app.sqlite_backend_gate import require_sqlite_read_authority, require_sqlite_production_activation
    def fail(**kwargs):raise ValueError('private path and token')
    monkeypatch.setattr(live,'validate_live_binding',fail)
    for gate in (require_sqlite_read_authority,require_sqlite_production_activation):
        with pytest.raises(RuntimeError) as error:gate(settings=prepared[-1])
        assert str(error.value)=='SQLite live release binding unavailable'


def test_public_live_worker_records_one_move_and_revalidates_advanced_state(prepared):
    from datetime import timedelta
    from app.sqlite_scheduled_production import production_cycle_step
    from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle
    from app.sqlite_scheduled_observations import ScheduledRunObservations
    from scripts.sqlite_scheduled_configured_slot_fixture import NOW
    case,source,control,_,values=prepared
    live.create_live_binding(settings=values)
    before=source.read_bytes();cycle=ScheduledWorkerCycle();observer=ScheduledRunObservations()
    def step(now):return production_cycle_step(cycle=cycle,settings=values,now=now,clock=lambda:NOW,observer=observer)
    assert step(case.fixture.slot-timedelta(hours=1)).status=='waiting'
    assert len(step(case.fixture.slot).outcome['completed'])==1
    assert observer.report()['last_result']=='completed'
    assert observer.history()[0]['dry_run'] is False
    calls=len(case.server.calls)
    assert step(case.fixture.slot+timedelta(seconds=1)).status=='waiting'
    assert len(case.server.calls)==calls and source.read_bytes()==before


def test_public_live_worker_uncertainty_is_failed_and_cannot_replay(prepared,monkeypatch):
    from datetime import timedelta
    from app.sqlite_scheduled_production import production_cycle_step
    from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle
    from app.sqlite_scheduled_observations import ScheduledRunObservations
    from scripts.sqlite_scheduled_configured_slot_fixture import NOW
    from app import sqlite_scheduled_routed_batch as batch
    case,_,control,_,values=prepared;live.create_live_binding(settings=values)
    original=batch.rename_directory_noreplace_at
    def uncertain(*args):original(*args);raise RuntimeError('fixture lost acknowledgement')
    monkeypatch.setattr(batch,'rename_directory_noreplace_at',uncertain)
    cycle=ScheduledWorkerCycle();observer=ScheduledRunObservations()
    def step(now):return production_cycle_step(cycle=cycle,settings=values,now=now,clock=lambda:NOW,observer=observer)
    step(case.fixture.slot-timedelta(hours=1))
    with pytest.raises(RuntimeError):step(case.fixture.slot)
    assert observer.report()['last_result']=='failed'
    calls=len(case.server.calls)
    with pytest.raises(RuntimeError):step(case.fixture.slot+timedelta(days=1))
    assert len(case.server.calls)==calls
