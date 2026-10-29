"""Live preparation preserves a verified preview without activating services."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from app import sqlite_release_profile as build
from app import sqlite_live_binding as live
from app.sqlite_live_policy import DISABLED
from app.state_store import GuardedSQLiteStateStore
from scripts import unraid_update_prepare_fixture as reference
identity=reference.identity
from scripts import unraid_live_prepare as prepare


@pytest.fixture
def case():
    current=reference.ReplacementPrepareTests();current.setUp()
    try:
        current.image['Config']['Labels']['io.media-collection-auditor.sqlite-activation']='scheduled-moves'
        yield current
    finally:current.doCleanups()


def run(case,**changes):
    args=dict(backup=case.backup,backup_identity=identity(case.backup),backup_fingerprint=case.fingerprint,
              logs=case.logs,logs_identity=identity(case.logs),control=case.control,control_identity=identity(case.control),
              candidate_image=case.image)
    args.update(changes)
    with patch.object(build,'PROFILE',live.PROFILE):return prepare.prepare_live_candidate(**args)


def test_live_preparation_preserves_clocks_unknowns_credentials_schedule_and_old_files(case):
    report=run(case)
    assert report['status']=='live_candidate_binding_prepared_not_started'
    assert report['initial_maximum_actions']==1 and report['media_actions_authorized'] is False
    assert 'fixture-private-secret' not in json.dumps(report)
    assert GuardedSQLiteStateStore(case.control/'release/state.db').load_with_revision()==(case.state,0)
    saved=json.loads((case.logs/'auditor_config.json').read_bytes())
    before=json.loads(case.saved.read_bytes())
    assert saved=={**before,'DRY_RUN':'false','MAX_ACTIONS_PER_RUN':'1',**{key:'false' for key in DISABLED}}
    env=dict(line.split('=',1) for line in (case.logs/'runtime.env').read_text().splitlines())
    with patch.object(build,'PROFILE',live.PROFILE):live.validate_live_binding(settings=env,for_execution=True)
    for key in ('SQLITE_DAILY_RUN_TIME','SQLITE_DAILY_RUN_TIMEZONE','JELLYFIN_API_TOKEN','ENABLE_TV'):
        assert env[key]==case.env[key]
    assert (case.logs/'retained-preview-config.json').read_bytes()==case.saved.read_bytes()
    case.unchanged()


@pytest.mark.parametrize('failure',['fingerprint','image','overlap','occupied'])
def test_invalid_selection_never_overwrites_existing_files(case,failure):
    changes={}
    if failure=='fingerprint':changes['backup_fingerprint']='f'*64
    elif failure=='image':
        changes['candidate_image']=deepcopy(case.image)
        changes['candidate_image']['Config']['Labels']['io.media-collection-auditor.sqlite-activation']='preview-only'
    elif failure=='overlap':changes.update(logs=case.backup,logs_identity=identity(case.backup))
    else:(case.logs/'keep').write_bytes(b'preserve')
    with pytest.raises((RuntimeError,ValueError)):run(case,**changes)
    assert not list(case.control.iterdir())
    assert list(case.logs.iterdir())==([case.logs/'keep'] if failure=='occupied' else [])
    case.unchanged()


@pytest.mark.parametrize('phase',['after_request','before_binding','after_binding','before_completion'])
def test_interruption_retained_without_completion_or_replay(case,phase):
    def stop(current):
        if current==phase:raise RuntimeError('fixture controller death')
    with patch.object(prepare,'_boundary',side_effect=stop):
        with pytest.raises(RuntimeError):run(case)
    assert (case.logs/prepare.REQUEST).exists() and not (case.logs/prepare.COMPLETE).exists()
    with pytest.raises(RuntimeError):run(case)
    case.unchanged()


@pytest.mark.parametrize('changed',['backup','config','environment','source'])
def test_final_mutation_is_not_reported_complete(case,changed):
    def mutate(phase):
        if phase!='before_completion':return
        target={'backup':case.backup/'tracking-snapshot.json','config':case.logs/'auditor_config.json',
                'environment':case.logs/'runtime.env','source':case.logs/'auditor_state.json'}[changed]
        target.write_bytes(target.read_bytes()+b' ')
    with patch.object(prepare,'_boundary',side_effect=mutate):
        with pytest.raises(RuntimeError):run(case)
    assert not (case.logs/prepare.COMPLETE).exists()
