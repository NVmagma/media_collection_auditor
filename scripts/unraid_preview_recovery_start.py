"""Explicit single-attempt start of a selected, stopped same-image replacement.

No stop, remove, automatic rollback, replay or binding edits are performed.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
from app.sqlite_json import parse_unique_json
from app.sqlite_release_recovery import _local
from app.sqlite_preview_install import _private_root
from app.sqlite_lock import _exclusive_lock
from scripts.sqlite_preview_service import (Docker, Journal, NAME, validate_original,
    validate_preview, verify_http_health)
from scripts.unraid_update_backup import load_backup_payloads
from scripts.unraid_update_production_prepare import replacement_metadata


def start_selected(*,engine,journal,captured,selection,payload,precheck,health,install):
    """Fixed order with durable intent before each external action."""
    old=captured['Id']; attempt=selection['attempt']
    archive=NAME+'_before_rebind_'+old[:12]
    validate_original(engine.inspect(NAME),captured,name=NAME,running=False)
    if engine.inspect(archive,optional=True) is not None: raise RuntimeError('Archive name occupied')
    precheck()
    journal.begin({'schema_version':1,'original_container_id':old,'attempt':attempt,
        'automatic_restoration':False,'media_actions_authorized':False})
    journal.event('original_archive_requested')
    engine.rename(old,archive)
    validate_original(engine.inspect(old),captured,name=archive,running=False)
    journal.event('original_archived')
    if engine.inspect(NAME,optional=True) is not None: raise RuntimeError('Replacement name occupied')
    precheck()
    journal.event('replacement_create_requested')
    identity=engine.create(NAME,payload)
    journal.event('replacement_created',container_id=identity)
    def check(running):
        validate_preview(engine.inspect(identity),identity=identity,image_id=selection['image_id'],
            request_id=attempt,payload=payload,running=running)
    check(False); precheck()
    journal.event('replacement_start_requested',container_id=identity)
    engine.start(identity); check(True)
    journal.event('replacement_started',container_id=identity)
    health(identity)
    journal.event('replacement_health_verified',container_id=identity)
    validate_original(engine.inspect(old),captured,name=archive,running=False)
    journal.event('template_install_requested')
    install(); check(True)
    journal.event('recovery_complete',container_id=identity)
    return {'status':'tv_preview_recovery_complete','container_id':identity,
        'original_container_retained':True,'automatic_restoration':False,'media_actions_authorized':False}


def execute(*,selection_fingerprint,backup_fingerprint,daemon_id,logs_identity,backup_identity):
    from app.sqlite_preview_activation import validate_preview_activation, BINDING
    from app.state_store import GuardedSQLiteStateStore
    from app.sqlite_preview_template import RUNTIME_DEFAULTS
    with ExitStack() as stack:
        logs=_private_root(Path('/app/logs'),logs_identity);stack.callback(os.close,logs)
        stack.enter_context(_exclusive_lock(Path('/app/logs/.recovery.lock'),'Recovery already active'))
        raw=_local(logs,'update-selection.json')[0]
        if hashlib.sha256(raw).hexdigest()!=selection_fingerprint: raise RuntimeError('Selection changed')
        selection=parse_unique_json(raw)
        if selection['backup_fingerprint']!=backup_fingerprint: raise RuntimeError('Backup changed')
        files={key:_local(logs,key)[0] for key in ('create-payload.json','replacement-template.xml')}
        for key,value in files.items():
            if hashlib.sha256(value).hexdigest()!=selection['sha256'][key]: raise RuntimeError('Prepared artifact changed')
        data=load_backup_payloads(directory=Path('/backup'),expected_identity=backup_identity,expected_fingerprint=backup_fingerprint)
        captured=parse_unique_json(data['current.inspect.json']);payload=parse_unique_json(files['create-payload.json'])
        engine=Docker(endpoint='/var/run/docker.sock',expected_daemon=daemon_id)
        image=engine.image(selection['reference'])
        env=dict(item.split('=',1) for item in payload['Env'])
        recreated,xml=replacement_metadata(current=captured,image=image,template=data['current-template.xml'],
            environment={key:value for key,value in env.items() if key not in RUNTIME_DEFAULTS},
            reference=selection['reference'],host_logs=selection['host_logs'],host_control=selection['host_control'],attempt=selection['attempt'])
        if recreated!=payload or xml!=files['replacement-template.xml']: raise RuntimeError('Metadata reconstruction failed')
        directory=Path('/templates'); target=directory/'my-media_collection_auditor.xml'
        original=data['current-template.xml']
        def template_check():
            # Inventory all saved templates; malformed/duplicate entries are unknown coverage.
            matches=[]
            from xml.etree import ElementTree as ET
            for path in directory.glob('*.xml'):
                content=path.read_bytes()
                if len(content)>2*1024*1024 or b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
                    raise RuntimeError('Template inventory needs review')
                root=ET.fromstring(content)
                if root.findtext('Name')==NAME: matches.append(path.name)
            if matches!=[target.name] or target.is_symlink() or target.read_bytes()!=original:
                raise RuntimeError('Saved template changed')
        def precheck():
            template_check()
            validate_preview_activation(settings=env)
            state,revision=GuardedSQLiteStateStore('/old-control/release/state.db').load_with_revision()
            if state!=parse_unique_json(data['tracking-snapshot.json']) or revision!=0:
                raise RuntimeError('Original tracking changed')
            if Path('/old-logs/auditor_state.json').read_bytes()!=data['retained-source.json']:
                raise RuntimeError('Original retained source changed')
            if (Path('/old-control/release')/BINDING).read_bytes()!=data['current-binding.json']:
                raise RuntimeError('Original binding changed')
            if Path('/old-logs/auditor_config.json').read_bytes()!=data['saved-config.json']:
                raise RuntimeError('Original settings changed')
            if load_backup_payloads(directory=Path('/backup'),expected_identity=backup_identity,expected_fingerprint=backup_fingerprint)!=data:
                raise RuntimeError('Backup changed')
        def install():
            template_check()
            temporary=directory/('.auditor-recovery-'+selection['attempt'])
            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as stream:
                stream.write(files['replacement-template.xml']);stream.flush();os.fsync(stream.fileno())
            template_check()
            os.replace(temporary,target)
            parent=os.open(directory,os.O_DIRECTORY|os.O_RDONLY)
            try: os.fsync(parent)
            finally: os.close(parent)
        return start_selected(engine=engine,journal=Journal(logs,prefix='recovery'),captured=captured,
            selection=selection,payload=payload,precheck=precheck,
            health=lambda identity:verify_http_health(engine=engine,identity=identity,env=env),install=install)


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    for key in ('selection-fingerprint','backup-fingerprint','daemon-id','logs-identity','backup-identity'):
        parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    def identity(value):
        if not re.fullmatch('[0-9]+:[0-9]+',value):raise ValueError('Directory identity required')
        return tuple(map(int,value.split(':')))
    try:
        for value in (args.selection_fingerprint,args.backup_fingerprint):
            if not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('Fingerprint required')
        result=execute(selection_fingerprint=args.selection_fingerprint,backup_fingerprint=args.backup_fingerprint,
            daemon_id=args.daemon_id,logs_identity=identity(args.logs_identity),backup_identity=identity(args.backup_identity))
    except Exception as error:
        print(json.dumps({'status':'recovery_stopped_for_review','error_type':type(error).__name__,
            'automatic_restoration':False,'media_actions_authorized':False}));return 2
    print(json.dumps(result,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
