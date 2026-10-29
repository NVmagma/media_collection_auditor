"""Offline live review binds current preview, native metadata and prepared state."""
from copy import deepcopy
import hashlib,json,os,shutil
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
import pytest
from app import sqlite_release_profile as build
from app.sqlite_preview_activation import validate_preview_activation,BINDING
from app.sqlite_preview_install import stage_preview
from app.sqlite_live_binding import PROFILE
from app.sqlite_release_preparation import _identity
from app.sqlite_release_recovery import _local
from app.sqlite_scheduled_paths import _open_directory
from app.state_store import GuardedSQLiteStateStore
from scripts import unraid_update_prepare_fixture as reference
from scripts.unraid_update_backup import capture_backup
from scripts.unraid_live_prepare import prepare_live_candidate
from scripts.unraid_live_review import review_live_candidate
from test_unraid_live_plan import values as plan_values

identity=reference.identity


@pytest.fixture
def case():
    case=reference.ReplacementPrepareTests();case.setUp()
    try:
        case.native=case.root/'native';case.native.mkdir()
        for prefix,folder in (('RADARR','Movies'),('SONARR','TV')):
            for stage,suffix in (('TRANSIENT',''),('HOLDING','_hold'),('KEEP','_keep'),('REMOVAL','_removal')):
                source=Path(case.env[prefix+'_'+stage+'_PATH']);target=case.native/(folder+suffix)
                shutil.copytree(source,target)
                case.env[prefix+'_'+stage+'_PATH']=str(target)
        case.env['MEDIA_PATH']=str(case.native)
        case.shared=case.root/'shared';shutil.copytree(case.native,case.shared)
        case.old_control=case.root/'review-original-control';case.old_control.mkdir(mode=0o700)
        case.env['SQLITE_STATE_FILE']=str(case.old_control/'release/state.db')
        with patch.object(build,'SOURCE_REVISION','a'*40):
            stage_preview(source=case.source,config=case.saved,control_root=case.old_control,
                expected_control_identity=identity(case.old_control),expected_config_sha256=hashlib.sha256(case.saved.read_bytes()).hexdigest(),
                proposed_config=json.loads(case.saved.read_bytes()),settings=case.env)
            shape=plan_values();case.current=shape['current']
            case.current.update(Id='a'*64,Image='sha256:'+'a'*64)
            observed_env={**case.env,'SQLITE_STATE_FILE':'/sqlite-control/release/state.db'}
            case.current['Config']['Env']=[key+'='+value for key,value in observed_env.items()]
            root=ET.fromstring(shape['template'])
            for item in list(root.findall('Config')):
                if item.get('Type')=='Variable':root.remove(item)
            for key,value in observed_env.items():ET.SubElement(root,'Config',Type='Variable',Target=key).text=value
            case.template=ET.tostring(root)
            case.backup=case.root/'review-backup';case.backup.mkdir(mode=0o700)
            def inputs():
                result={}
                for name,path in (('saved-config.json',case.saved),('retained-source.json',case.source),
                                  ('current-binding.json',case.old_control/'release'/BINDING)):
                    fd=_open_directory(str(path.parent))
                    try:
                        raw,info=_local(fd,path.name);result[name]=(raw,_identity(info))
                    finally:os.close(fd)
                return result
            capture_backup(directory=case.backup,expected_identity=identity(case.backup),container=case.current,
                template=case.template,source_revision='a'*40,validate_current=lambda:validate_preview_activation(settings=case.env),
                read_snapshot=lambda:GuardedSQLiteStateStore(case.old_control/'release/state.db').load_with_revision(),read_inputs=inputs)
        case.fingerprint=hashlib.sha256((case.backup/'backup-complete.json').read_bytes()).hexdigest()
        case.image['Config']['Labels']['io.media-collection-auditor.sqlite-activation']='scheduled-moves'
        case.reference='ghcr.io/nvmagma/media_collection_auditor@sha256:'+'c'*64
        case.image['RepoDigests']=[case.reference]
        with patch.object(build,'PROFILE',PROFILE):
            prepare_live_candidate(backup=case.backup,backup_identity=identity(case.backup),backup_fingerprint=case.fingerprint,
                logs=case.logs,logs_identity=identity(case.logs),control=case.control,control_identity=identity(case.control),candidate_image=case.image)
        case.output=case.root/'review-output';case.output.mkdir(mode=0o700)
        case.templates=[('current.xml',case.template)]
        yield case
    finally:case.doCleanups()


def run(case,**changes):
    args=dict(backup=case.backup,backup_identity=identity(case.backup),fingerprint=case.fingerprint,
        logs=case.logs,control=case.control,old_logs=case.root,old_control=case.old_control,
        output=case.output,output_identity=identity(case.output),live=case.current,image=case.image,
        host_logs='/new-private/logs',host_control='/new-private/control',host_media='/native-pool/media_storage',
        shared_media=case.shared,native_media=case.native,reference=case.reference,templates=lambda:case.templates)
    args.update(changes)
    with patch.object(build,'PROFILE',PROFILE):return review_live_candidate(**args)


def test_review_writes_only_private_proposal_and_no_installation_authority(case):
    before=GuardedSQLiteStateStore(case.control/'release/state.db').load_with_revision()
    original=case.source.read_bytes();saved=case.saved.read_bytes()
    report=run(case)
    assert report['status']=='live_cutover_review_prepared' and not report['deployment_authorized']
    assert report['native_view_metadata_matches'] and not report['byte_equality_verified']
    assert report['media_read_only'] is False and report['permanent_deletion_authorized'] is False
    assert 'fixture-private-secret' not in json.dumps(report)
    assert GuardedSQLiteStateStore(case.control/'release/state.db').load_with_revision()==before
    assert case.source.read_bytes()==original and case.saved.read_bytes()==saved
    assert (case.output/'review-complete.json').exists()
    payload=json.loads((case.output/'proposed-container.json').read_bytes())
    assert next(item for item in payload['HostConfig']['Mounts'] if item['Target']=='/media')['ReadOnly'] is False
    assert case.templates==[('current.xml',case.template)]


@pytest.mark.parametrize('change',['current-settings','current-source','new-config','new-environment','native-missing-title',
                                   'duplicate-template','occupied-review','published-reference'])
def test_changed_inputs_block_review_before_completion(case,change):
    args={}
    if change=='current-settings':case.saved.write_bytes(case.saved.read_bytes()+b' ')
    elif change=='current-source':case.source.write_bytes(case.source.read_bytes()+b' ')
    elif change=='new-config':(case.logs/'auditor_config.json').write_bytes(b'{}')
    elif change=='new-environment':(case.logs/'runtime.env').write_bytes(b'DRY_RUN=true\n')
    elif change=='native-missing-title':(case.native/'Movies'/'unexpected-title').mkdir()
    elif change=='duplicate-template':case.templates.append(('duplicate.xml',case.template))
    elif change=='occupied-review':(case.output/'keep').write_bytes(b'preserve')
    else:args['reference']=case.reference+'bad'
    with pytest.raises((RuntimeError,ValueError)):run(case,**args)
    assert not (case.output/'review-complete.json').exists()
