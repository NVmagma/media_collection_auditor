"""Private live cutover review/freshness observation only; no Docker socket or service calls."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
from app.sqlite_json import parse_unique_json
from app.sqlite_preview_install import _private_root
from app.sqlite_release_recovery import _local,_encode
from app.sqlite_release_preparation import _identity
from app.sqlite_scheduled_paths import _open_directory
from app.sqlite_disposable_restore import _write_private
from scripts.unraid_update_backup import load_backup_payloads
from scripts.unraid_live_plan import live_metadata
from scripts.sqlite_preview_service import validate_original


def _capture(root,names):
    fd=_open_directory(str(root))
    try:return {name:(raw,_identity(info)) for name in names for raw,info in [_local(fd,name)]}
    finally:os.close(fd)


def _environment(raw):
    values={}
    for line in raw.decode().splitlines():
        key,separator,value=line.partition('=')
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',key) or key in values:
            raise ValueError('Unique prepared environment required')
        values[key]=value
    return values


def review_live_candidate(*,backup,backup_identity,fingerprint,logs,control,old_logs,old_control,
                     output,output_identity,live,image,host_logs,host_control,templates,reference,host_media,shared_media,native_media,diagnostic=None):
    from app.sqlite_tracking_view import _candidate_capture
    from app.sqlite_live_binding import validate_live_binding,_revision
    from app.sqlite_preview_activation import BINDING
    from app.sqlite_live_policy import DISABLED,validate_initial_live_policy
    from app.sqlite_media_view_review import compare_media_views
    from app.sqlite_preview_template import RUNTIME_DEFAULTS
    from app.sqlite_state import SECTIONS
    from app.unraid_update_review import matching_templates
    def stage(name):
        if diagnostic is not None:diagnostic(name)
    stage('published_image')
    if reference is not None:
        from scripts.unraid_update_production_prepare import REFERENCE
        if not REFERENCE.fullmatch(reference) or reference not in (image.get('RepoDigests') or []):
            raise ValueError('Published reference must resolve to the selected cached image')
    selected=dict(directory=backup,expected_identity=backup_identity,expected_fingerprint=fingerprint)
    stage('backup_packet')
    data=load_backup_payloads(**selected)
    original=parse_unique_json(data['current.inspect.json'])
    stage('current_container')
    validate_original(live,original,name='media_collection_auditor',running=original['State']['Running'])
    stage('template_inventory')
    before_templates=templates()
    matches=matching_templates(before_templates)
    if len(matches)!=1 or next(raw for name,raw in before_templates if name==matches[0][0])!=data['current-template.xml']:
        raise RuntimeError('Unique unchanged managed template required')
    original_env=dict(item.split('=',1) for item in original['Config']['Env'])
    source_path=Path(original_env.get('STATE_FILE','/app/logs/auditor_state.json'))
    config_path=Path(original_env.get('WEB_CONFIG_FILE','/app/logs/auditor_config.json'))
    if not source_path.is_absolute() or source_path.parent!=config_path.parent or source_path.name==config_path.name:
        raise RuntimeError('Distinct source/settings in one known logs root required')
    stage('current_retained_inputs')
    old_before=_capture(old_logs,(source_path.name,config_path.name))
    from app.sqlite_release_preparation import REQUEST
    old_binding=_capture(old_control/'release',(BINDING,REQUEST))
    binding=parse_unique_json(old_binding[BINDING][0]);source_request=parse_unique_json(old_binding[REQUEST][0])
    if (hashlib.sha256(old_binding[REQUEST][0]).hexdigest()!=binding.get('prepared_inputs',{}).get(REQUEST)
            or source_request.get('source_identity')!=list(old_before[source_path.name][1])):
        raise RuntimeError('Original retained source identity/provenance changed')
    if (old_before[source_path.name][0]!=data['retained-source.json']
            or old_before[config_path.name][0]!=data['saved-config.json']
            or old_binding[BINDING][0]!=data['current-binding.json']):
        raise RuntimeError('Current source/settings/binding changed since capture')
    stage('prepared_files')
    new_before=_capture(logs,('runtime.env','auditor_state.json','auditor_config.json',
        'retained-preview-config.json','live-preparation-request.json','live-preparation-complete.json'))
    prepared=parse_unique_json(new_before['live-preparation-complete.json'][0])
    if (prepared.get('candidate_image_id')!=image['Id'] or prepared.get('source_revision')!=_revision()
            or prepared.get('backup_fingerprint')!=fingerprint or prepared.get('status')!='live_candidate_binding_prepared_not_started'):
        raise RuntimeError('Prepared candidate selection changed')
    stage('prepared_configuration')
    env=_environment(new_before['runtime.env'][0])
    expected={key:value for key,value in (item.split('=',1) for item in original['Config']['Env']) if key not in RUNTIME_DEFAULTS}
    expected.update(STATE_FILE=str(logs/'auditor_state.json'),WEB_CONFIG_FILE=str(logs/'auditor_config.json'),SQLITE_STATE_FILE=str(control/'release'/'state.db'))
    changes={'DRY_RUN':'false','MAX_ACTIONS_PER_RUN':'1',**{key:'false' for key in DISABLED}}
    expected.update(changes,AUDITOR_STATE_BACKEND='sqlite',READ_ONLY_API_SERVICE='false')
    saved=parse_unique_json(data['saved-config.json'])
    if (env!=expected or parse_unique_json(new_before['auditor_config.json'][0])!={**saved,**changes}
            or new_before['retained-preview-config.json'][0]!=data['saved-config.json']):
        raise RuntimeError('Prepared settings/environment changed')
    state=parse_unique_json(data['tracking-snapshot.json'])
    if parse_unique_json(new_before['auditor_state.json'][0])!=state:
        raise RuntimeError('Prepared retained snapshot changed')
    stage('tracking_snapshots')
    with ExitStack() as stack:
        old=stack.enter_context(_candidate_capture(old_control/'release'/'state.db'))
        new=stack.enter_context(_candidate_capture(control/'release'/'state.db'))
        if old.state!=state or old.revision!=0 or new.state!=state or new.revision!=0:
            raise RuntimeError('Current or prepared tracking changed')
        stage('live_binding')
        validate_live_binding(settings=env,for_execution=True)
        effective=validate_live_binding(settings=env,for_execution=True)
        stage('native_stage_layout')
        policy=validate_initial_live_policy(effective)
        if effective.get('MEDIA_PATH','/media')!=str(native_media):
            raise RuntimeError('Native view must cover configured media base')
        names={'Waiting':'','Holding':'_hold','Keep':'_keep','Removal':'_removal'}
        if any(path!=str(Path(native_media)/(library.name+names[stage]))
               for library in policy.libraries for stage,path in library.roots):
            raise RuntimeError('Initial native review requires standard stage layout')
        stage('native_view_comparison')
        view=compare_media_views(shared=shared_media,native=native_media)
        if not view.get('all_stage_metadata_matches') or not view.get('native_stages_one_mount_and_device'):
            raise RuntimeError('Shared/native media views require review')
        stage('container_template_proposal')
        payload,xml=live_metadata(current=live,image=image,template=data['current-template.xml'],
            environment=env,reference=reference,host_logs=host_logs,host_control=host_control,
            host_media=host_media,attempt=os.urandom(32).hex(),effective_settings=effective,diagnostic=stage)
        def unchanged():
            if (_capture(old_logs,tuple(old_before))!=old_before
                    or _capture(old_control/'release',tuple(old_binding))!=old_binding
                    or _capture(logs,tuple(new_before))!=new_before or templates()!=before_templates
                    or load_backup_payloads(**selected)!=data):
                raise RuntimeError('Review inputs changed during capture')
            old.verify_current();new.verify_current();validate_live_binding(settings=env,for_execution=True)
        stage('final_input_recheck')
        unchanged()
        fd=_private_root(Path(output),output_identity);stack.callback(os.close,fd)
        if os.listdir(fd):raise RuntimeError('New empty review directory required')
        stage('private_proposal_write')
        _write_private(fd,'proposed-container.json',_encode(payload))
        _write_private(fd,'proposed-template.xml',xml)
        unchanged()
        report={'schema_version':1,'status':'live_cutover_review_prepared','source_revision':_revision(),
            'candidate_image_id':image['Id'],'original_container_id':live['Id'],'original_running':live['State']['Running'],
            'backup_fingerprint':fingerprint,'backup_matches_current_observation':True,
            'writer_quiescence_verified':False,'tracking_preserved':True,'settings_preserved_except_canary_controls':True,
            'tracking_counts':{key:len(state.get(key,{})) for key in SECTIONS},
            'media_read_only':False,'native_media_host_path':host_media,'native_view_metadata_matches':True,
            'byte_equality_verified':False,'container_user':'0:0','capabilities_dropped':'ALL',
            'capabilities_added':['DAC_OVERRIDE'],'initial_maximum_actions':1,'permanent_deletion_authorized':False,'root_filesystem_read_only':True,'network_mode':payload['HostConfig']['NetworkMode'],
            'environment_entries':len(payload['Env']),'published_ports':payload['HostConfig'].get('PortBindings',{}),
            'template_matches_current':True,'template_installed':False,
            'image_reference_status':'verified_cached_digest',
            'reference':reference,'executable_payload_prepared':False,
            'deployment_authorized':False,'service_changes_performed':False,'automatic_restoration':False,
            'sha256':{'proposed-container.json':hashlib.sha256(_encode(payload)).hexdigest(),
                      'proposed-template.xml':hashlib.sha256(xml).hexdigest()}}
    # Complete only after both database context managers verify and close.
    stage('review_completion')
    fd=_private_root(Path(output),output_identity)
    try:_write_private(fd,'review-complete.json',_encode(report))
    finally:os.close(fd)
    return report


def main():
    import argparse,sys
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    for key in ('backup-identity','fingerprint','output-identity','host-logs','host-control','host-media'):
        parser.add_argument('--'+key,required=True)
    parser.add_argument('--reference',required=True)
    args=parser.parse_args()
    def identity(raw):
        if not re.fullmatch(r'[0-9]{1,20}:[0-9]{1,20}',raw):raise ValueError('Directory identity required')
        return tuple(map(int,raw.split(':')))
    def templates():
        root=Path('/templates');fd=_open_directory(str(root))
        try:
            names=sorted(name for name in os.listdir(fd) if name.endswith('.xml'))
            if len(names)>256:raise ValueError('Bounded template inventory required')
            return [(name,_local(fd,name)[0]) for name in names]
        finally:os.close(fd)
    diagnostic_stage=['input_metadata']
    try:
        raw=sys.stdin.buffer.read(16*1024*1024+1)
        if len(raw)>16*1024*1024:raise ValueError('Bounded metadata required')
        metadata=parse_unique_json(raw)
        if len(metadata['containers'])!=1 or len(metadata['images'])!=1:raise ValueError('Single selected container/image required')
        report=review_live_candidate(backup=Path('/backup'),backup_identity=identity(args.backup_identity),fingerprint=args.fingerprint,
            logs=Path('/app/logs'),control=Path('/sqlite-control'),old_logs=Path('/old-logs'),old_control=Path('/old-control'),
            output=Path('/review'),output_identity=identity(args.output_identity),live=metadata['containers'][0],
            image=metadata['images'][0],host_logs=args.host_logs,host_control=args.host_control,templates=templates,reference=args.reference,
            host_media=args.host_media,shared_media=Path('/shared-media'),native_media=Path('/media'),
            diagnostic=lambda value:diagnostic_stage.__setitem__(0,value))
    except Exception as error:
        kind=type(error).__name__
        if kind not in ('RuntimeError','ValueError','FileNotFoundError','PermissionError','OSError','KeyError','TypeError'):kind='validation_error'
        allowed={'unraid_live_review.py','unraid_live_plan.py','sqlite_live_binding.py','sqlite_preview_install.py','sqlite_release_recovery.py','sqlite_tracking_view.py'}
        sites=[];trace=error.__traceback__
        while trace is not None:
            name=Path(trace.tb_frame.f_code.co_filename).name
            if name in allowed:sites.append({'file':name,'line':trace.tb_lineno})
            trace=trace.tb_next
        print(json.dumps({'status':'live_review_blocked','diagnostic_stage':diagnostic_stage[0],'error_type':kind,'failure_sites':sites[-4:],'deployment_authorized':False,
            'service_changes_performed':False,'partial_review_retained':True}));return 2
    print(json.dumps(report,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
