"""Live-to-live review uses real bound state and preserves the existing native view."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from app import sqlite_release_profile as build
from app.sqlite_live_binding import PROFILE, BINDING, validate_live_binding
from app.sqlite_release_preparation import _identity
from app.sqlite_release_recovery import _local
from app.sqlite_scheduled_paths import _open_directory
from app.state_store import GuardedSQLiteStateStore
from scripts import unraid_live_update_backup as backup
from scripts.unraid_live_prepare import prepare_live_candidate
from scripts.unraid_live_review import review_live_candidate
from test_unraid_live_review import case, run as initial_review, identity


@pytest.fixture
def update_case(case, monkeypatch):
    monkeypatch.setattr(build, 'PROFILE', PROFILE)
    initial_review(case)
    payload=json.loads((case.output/'proposed-container.json').read_bytes())
    template=ET.fromstring((case.output/'proposed-template.xml').read_bytes())
    old_logs,old_control=case.logs,case.control
    values=dict(line.split('=',1) for line in (old_logs/'runtime.env').read_text().splitlines())
    observed=dict(values, STATE_FILE='/app/logs/auditor_state.json',
                  WEB_CONFIG_FILE='/app/logs/auditor_config.json', SQLITE_STATE_FILE='/sqlite-control/release/state.db')
    current={'Id':'b'*64,'Image':case.image['Id'],'Name':'/media_collection_auditor','State':{'Running':True},
             'Config':{key:deepcopy(value) for key,value in payload.items() if key!='HostConfig'},
             'HostConfig':deepcopy(payload['HostConfig'])}
    current['Config']['Env']=[key+'='+value for key,value in observed.items()]
    current['HostConfig']['CapAdd']=['CAP_DAC_OVERRIDE']
    current['Mounts']=[{'Type':'bind','Destination':row['Target'],'Source':row['Source'],
                       'RW':not row['ReadOnly'],'Propagation':row['BindOptions']['Propagation']}
                      for row in payload['HostConfig']['Mounts']]
    for row in template.findall('Config'):
        if row.get('Type')=='Variable': row.text=observed[row.get('Target')]
    raw_template=ET.tostring(template)
    store=GuardedSQLiteStateStore(old_control/'release/state.db')
    state,revision=store.load_with_revision();state['latest-extension']={'clock':'2026-10-30T02:00:00'}
    store.save_if_revision(state,revision)
    slots=old_control/'release/.sqlite_scheduled_slots';slots.mkdir(mode=0o700)
    for name,raw in [('1'*64+'.json',b'{"slot":"retained"}'),('2'*64+'.json',b'')]:
        path=slots/name;path.write_bytes(raw);path.chmod(0o600)
    packet=case.root/'live-update-backup';packet.mkdir(mode=0o700)
    def inputs():
        result={}
        for name,path in (('saved-config.json',old_logs/'auditor_config.json'),
                ('retained-source.json',old_logs/'auditor_state.json'),
                ('current-binding.json',old_control/'release'/BINDING)):
            fd=_open_directory(str(path.parent))
            try:
                raw,info=_local(fd,path.name);result[name]=(raw,_identity(info))
            finally:os.close(fd)
        return result
    backup.capture_backup(directory=packet,expected_identity=identity(packet),container=current,
        template=raw_template,source_revision='b'*40,
        validate_current=lambda:validate_live_binding(settings=values,for_execution=True),
        read_snapshot=store.load_with_revision,read_inputs=inputs,
        read_claims=lambda:backup.read_daily_claims(old_control/'release'))
    image=deepcopy(case.image);image['Id']='sha256:'+'d'*64
    image['Config']['Labels']['org.opencontainers.image.revision']='d'*40
    reference='ghcr.io/nvmagma/media_collection_auditor@sha256:'+'e'*64;image['RepoDigests']=[reference]
    monkeypatch.setattr(build,'SOURCE_REVISION','d'*40)
    logs=case.root/'live-update-logs';logs.mkdir(mode=0o700)
    control=case.root/'live-update-control';control.mkdir(mode=0o700)
    fingerprint=hashlib.sha256((packet/'backup-complete.json').read_bytes()).hexdigest()
    prepare_live_candidate(backup=packet,backup_identity=identity(packet),backup_fingerprint=fingerprint,
        logs=logs,logs_identity=identity(logs),control=control,control_identity=identity(control),
        candidate_image=image,_live_update=True)
    output=case.root/'live-update-review';output.mkdir(mode=0o700)
    case.backup,case.fingerprint,case.image,case.reference=packet,fingerprint,image,reference
    case.logs,case.control,case.output=logs,control,output
    case.current,case.template,case.templates=current,raw_template,[('current.xml',raw_template)]
    case.old_logs,case.old_control=old_logs,old_control
    return case


def run(case,**changes):
    args=dict(backup=case.backup,backup_identity=identity(case.backup),fingerprint=case.fingerprint,
        logs=case.logs,control=case.control,old_logs=case.old_logs,old_control=case.old_control,
        output=case.output,output_identity=identity(case.output),live=case.current,image=case.image,
        host_logs='/update-private/logs',host_control='/update-private/control',
        host_media='/native-pool/media_storage',shared_media=case.native,native_media=case.native,
        reference=case.reference,templates=lambda:case.templates,_live_update=True)
    args.update(changes)
    return review_live_candidate(**args)


def test_review_preserves_advanced_state_claims_settings_and_existing_native_bind(update_case):
    case=update_case;stages=[]
    try:report=run(case,diagnostic=stages.append)
    except RuntimeError:pytest.fail('Review stages: '+repr(stages))
    assert report['status']=='live_update_cutover_review_prepared'
    assert report['daily_claims_preserved'] and report['daily_claim_count']==2
    assert report['source_snapshot_revision']==1 and report['media_binding_preserved']
    assert report['native_view_metadata_matches'] is None
    assert not report['deployment_authorized'] and not report['service_changes_performed']
    payload=json.loads((case.output/'proposed-container.json').read_bytes())
    media=next(row for row in payload['HostConfig']['Mounts'] if row['Target']=='/media')
    assert media['Source']=='/native-pool/media_storage' and not media['ReadOnly']
    assert payload['HostConfig']['CapAdd']==['DAC_OVERRIDE']


@pytest.mark.parametrize('change',['old_claim','new_claim','old_state','old_database_replaced',
                                  'new_state','old_source','settings','wrong_native','duplicate_template'])
def test_changed_inputs_prevent_completed_update_review(update_case,change):
    case=update_case;args={}
    if change in ('old_claim','new_claim'):
        control=case.old_control if change=='old_claim' else case.control
        path=control/'release/.sqlite_scheduled_slots'/('3'*64+'.json');path.write_bytes(b'');path.chmod(0o600)
    elif change in ('old_state','new_state'):
        control=case.old_control if change=='old_state' else case.control
        store=GuardedSQLiteStateStore(control/'release/state.db');state,revision=store.load_with_revision()
        state['later']=True;store.save_if_revision(state,revision)
    elif change=='old_database_replaced':
        path=case.old_control/'release/state.db';raw=path.read_bytes()
        path.rename(path.with_name('retained.db'));path.write_bytes(raw)
    elif change=='old_source':
        path=case.old_logs/'auditor_state.json';path.write_bytes(path.read_bytes()+b' ')
    elif change=='settings':
        path=case.logs/'auditor_config.json';path.write_bytes(path.read_bytes()+b' ')
    elif change=='wrong_native':args['host_media']='/different-native'
    else:case.templates.append(('duplicate.xml',case.template))
    with pytest.raises((RuntimeError,ValueError)):run(case,**args)
    assert not (case.output/'review-complete.json').exists()
