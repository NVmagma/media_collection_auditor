"""Build a private JSON cutover proposal. Never call Docker or install a template."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
from xml.etree import ElementTree as ET

from app.config_store import DEFAULTS, KEYS
from app.json_scan_control import KEY
from app.json_worker_cycle import validate_policy
from app.json_worker_migration import latest_archived_start
from app.sqlite_json import parse_unique_json
from app.sqlite_release_recovery import _local, _encode
from app.sqlite_release_preparation import _identity
from app.sqlite_preview_install import _private_root
from app.sqlite_disposable_restore import _write_private
from app.sqlite_scheduled_paths import _open_directory
from app.unraid_update_review import matching_templates, review_update, parse_template
from scripts.json_cutover_prepare import COMPLETE, _environment
from scripts.sqlite_preview_service import LABEL, validate_original
from scripts.unraid_live_update_backup import load_backup_payloads

REFERENCE=re.compile(r'ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}')
PREPARED=('json-preparation-request.json','source-tracking.json','scan-claims-archive.json',
          'source-config.json','runtime.env','logs/auditor_state.json','logs/auditor_config.json')


def private_files(root, *, capture_identity=False):
    fd=_open_directory(str(root)); logs=None
    try:
        logs=_open_directory(str(Path(root)/'logs'))
        captured={name:_local(logs if name.startswith('logs/') else fd,name.split('/')[-1])
                  for name in (*PREPARED,COMPLETE)}
        values={name:raw for name,(raw,info) in captured.items()}
        identities={name:_identity(info) for name,(raw,info) in captured.items()}
        identities['root']=_identity(os.fstat(fd))[:2]
        identities['logs']=_identity(os.fstat(logs))[:2]
        for path,expected in ((root,identities['root']),(Path(root)/'logs',identities['logs'])):
            reopened=_open_directory(str(path))
            try:
                if _identity(os.fstat(reopened))[:2]!=expected: raise RuntimeError('Preparation directory replaced')
            finally: os.close(reopened)
        return (values,identities) if capture_identity else values
    finally:
        if logs is not None: os.close(logs)
        os.close(fd)


def verify_prepared(*, files, payloads, receipt, image, fingerprint):
    report=parse_unique_json(files[COMPLETE]); config=image.get('Config',{}); labels=config.get('Labels') or {}
    if (report.get('status')!='json_replacement_prepared_not_started'
            or report.get('candidate_image_id')!=image['Id'] or report.get('backup_fingerprint')!=fingerprint
            or report.get('source_revision')!=labels.get('org.opencontainers.image.revision')
            or labels.get('io.media-collection-auditor.worker')!='json-serialized'
            or config.get('Entrypoint')!=['python','-B','-m','app.main'] or config.get('Cmd') not in (None,[])
            or config.get('StopSignal')!='SIGINT' or config.get('Volumes') not in (None,{})
            or report.get('sha256')!={name:hashlib.sha256(files[name]).hexdigest() for name in PREPARED}):
        raise RuntimeError('Complete unchanged JSON preparation required')
    original=parse_unique_json(payloads['current.inspect.json'])
    if (report.get('original_container_id')!=original['Id'] or report.get('original_image_id')!=original['Image']
            or report.get('source_snapshot_revision')!=receipt['snapshot_revision']
            or report.get('original_source_revision')!=receipt['source_revision']):
        raise RuntimeError('Preparation provenance changed')
    for name,source in [('source-tracking.json','tracking-snapshot.json'),('source-config.json','saved-config.json'),
                        ('scan-claims-archive.json','daily-claims.json')]:
        if files[name]!=payloads[source]: raise RuntimeError('Retained backup parity changed')
    state=parse_unique_json(payloads['tracking-snapshot.json']); saved=parse_unique_json(payloads['saved-config.json'])
    expected_env=_environment(original)
    expected_env.update(AUDITOR_STATE_BACKEND='json',AUDITOR_WORKER_MODE='json_serialized',
        STATE_FILE='/app/logs/auditor_state.json',WEB_CONFIG_FILE='/app/logs/auditor_config.json',DRY_RUN='false',MAX_ACTIONS_PER_RUN='10')
    for key in ('ALLOW_PERMANENT_DELETE','ALLOW_FILESYSTEM_DELETE','ALLOW_CROSS_FILESYSTEM_MOVES','ENABLE_SEASON_PRUNING'):
        expected_env[key]='false'
    expected_raw=''.join(key+'='+value+'\n' for key,value in sorted(expected_env.items())).encode()
    if files['runtime.env']!=expected_raw or parse_unique_json(files['logs/auditor_config.json'])!={**saved,'MAX_ACTIONS_PER_RUN':'10'}:
        raise RuntimeError('Prepared settings differ from reviewed policy')
    effective={**DEFAULTS,**expected_env,**{key:str(value) for key,value in saved.items() if key in KEYS},'MAX_ACTIONS_PER_RUN':'10'}
    validate_policy(effective)
    zone=effective.get('SQLITE_DAILY_RUN_TIMEZONE') or effective.get('TZ') or 'UTC'
    latest=latest_archived_start(parse_unique_json(payloads['daily-claims.json']),timezone_name=zone)
    expected_state={**state,KEY:dict(schema_version=1,last_started_at=latest.isoformat(),last_result='imported',trigger='imported',journal=None)}
    if parse_unique_json(files['logs/auditor_state.json'])!=expected_state:
        raise RuntimeError('Prepared tracking or cooldown differs')
    return expected_env,report


def metadata(*,current,image,template,environment,host_logs,reference,attempt):
    if (not REFERENCE.fullmatch(reference or '') or reference not in (image.get('RepoDigests') or [])
            or not re.fullmatch(r'[0-9a-f]{64}',attempt or '') or image.get('Id')==current.get('Image')):
        raise ValueError('Exact published different candidate required')
    observed=review_update(templates=[('current.xml',template)],container=current,_live_canary=True)
    if observed['blockers']: raise RuntimeError('Current template does not match reviewed live container')
    old=current['Mounts']; targets={item['Destination']:item for item in old}
    if (len(old)!=3 or set(targets)!={'/media','/app/logs','/sqlite-control'}
            or any(item.get('Type')!='bind' or item.get('RW') is not True or item.get('Propagation','rprivate')!='rprivate' for item in old)):
        raise ValueError('Exact reviewed current mounts required')
    path=PurePosixPath(host_logs)
    if (not path.is_absolute() or str(path)!=host_logs or '..' in path.parts
            or any(ord(c)<=32 or c in ',<>' for c in host_logs)):
        raise ValueError('Canonical private logs required')
    for item in old:
        source=PurePosixPath(item['Source'])
        if path==source or path in source.parents or source in path.parents:
            raise ValueError('New logs overlap current bind')
    host=deepcopy(current['HostConfig']); payload=deepcopy(current['Config']); root=parse_template(template)
    if (host.get('ReadonlyRootfs') is not True or host.get('Privileged') is not False
            or host.get('RestartPolicy',{}).get('Name')!='no' or host.get('NetworkMode')!='bridge'
            or host.get('VolumesFrom') or host.get('Devices') or host.get('DeviceRequests')
            or host.get('CapDrop')!=['ALL'] or host.get('CapAdd') not in (['DAC_OVERRIDE'],['CAP_DAC_OVERRIDE'])
            or payload.get('Healthcheck')):
        raise ValueError('Reviewed capability and runtime policy required')
    security=host.get('SecurityOpt') or []
    if (not any(value in ('no-new-privileges','no-new-privileges:true') for value in security)
            or any(value not in ('no-new-privileges','no-new-privileges:true','label=disable') for value in security)):
        raise ValueError('Reviewed security options required')
    args=shlex.split(root.findtext('ExtraParams') or '')
    allowed=('--pull=','--tmpfs=','--hostname=','--domainname=','--memory=','--memory-swap=',
             '--memory-reservation=','--pids-limit=','--cpu-shares=','--cpu-period=','--cpu-quota=',
             '--cpus=','--cpuset-cpus=','--memory-swappiness=','--cgroupns=','--dns=','--dns-option=',
             '--dns-search=','--add-host=','--log-driver=','--log-opt=')
    exact={'--read-only','--user=0:0','--restart=no','--cap-drop=ALL','--cap-add=DAC_OVERRIDE',
           '--security-opt=no-new-privileges','--security-opt=no-new-privileges:true','--security-opt=label=disable'}
    if any(value not in exact and not value.startswith(allowed) for value in args):
        raise ValueError('Unsupported template arguments')
    runtime=dict(value.split('=',1) for value in image['Config'].get('Env',[])); runtime.update(environment)
    labels={key:value for key,value in (payload.get('Labels') or {}).items()
            if not key.startswith(('org.opencontainers.image.','io.media-collection-auditor.'))}
    labels.update(image['Config'].get('Labels') or {})
    labels[LABEL]=attempt
    webui='http://[IP]:[PORT:'+environment.get('WEB_PORT','8080')+']/'
    labels['net.unraid.docker.webui']=webui
    payload.update(Image=reference,User='0:0',WorkingDir='/app',Entrypoint=['python','-B','-m','app.main'],
        Cmd=None,StopSignal='SIGINT',Volumes=None,Env=[key+'='+value for key,value in sorted(runtime.items())],Labels=labels)
    host['Binds']=None
    host['Mounts']=[dict(Type='bind',Source=targets['/media']['Source'],Target='/media',ReadOnly=False,BindOptions={'Propagation':'rprivate'}),
                    dict(Type='bind',Source=host_logs,Target='/app/logs',ReadOnly=False,BindOptions={'Propagation':'rprivate'})]
    payload['HostConfig']=host
    root.find('Repository').text=reference
    for item in list(root.findall('Config')):
        kind,target=item.get('Type'),item.get('Target')
        if kind in ('Variable','Label') or (kind=='Path' and target=='/sqlite-control'): root.remove(item)
        elif kind=='Path' and target=='/app/logs': item.text=host_logs; item.set('Default',host_logs)
    for kind,values in [('Variable',environment),('Label',labels)]:
        for key,value in sorted(values.items()):
            if not isinstance(value,str) or any(ord(c)<32 for c in value): raise ValueError('Lossless template values required')
            item=ET.SubElement(root,'Config',Type=kind,Target=key,Name=key,Mode='',Display='advanced',Required='false',Mask='true' if kind=='Variable' else 'false',Default=value)
            item.text=value
    if root.find('WebUI') is None: ET.SubElement(root,'WebUI')
    root.find('WebUI').text=webui
    return payload,ET.tostring(root,encoding='utf-8',xml_declaration=True)+b'\n'


def review(*,backup,backup_identity,fingerprint,prepared,current,image,templates,host_logs,reference,output,output_identity):
    selected=dict(directory=Path(backup),expected_identity=backup_identity,expected_fingerprint=fingerprint)
    payloads,receipt=load_backup_payloads(**selected)
    original=parse_unique_json(payloads['current.inspect.json'])
    validate_original(current,original,name='media_collection_auditor',running=True)
    matches=matching_templates(templates)
    if len(matches)!=1: raise RuntimeError('Unique current template required')
    name=matches[0][0]; template=next(raw for filename,raw in templates if filename==name)
    if template!=payloads['current-template.xml']: raise RuntimeError('Saved template changed since backup')
    files,identities=private_files(prepared,capture_identity=True)
    environment,preparation=verify_prepared(files=files,payloads=payloads,receipt=receipt,image=image,fingerprint=fingerprint)
    payload,xml=metadata(current=current,image=image,template=template,environment=environment,
        host_logs=host_logs,reference=reference,attempt=os.urandom(32).hex())
    raw=_encode(payload)
    report=dict(schema_version=1,status='json_cutover_review_prepared',candidate_image_id=image['Id'],reference=reference,
        source_revision=preparation['source_revision'],original_container_id=current['Id'],backup_fingerprint=fingerprint,
        source_snapshot_revision=receipt['snapshot_revision'],tracking_counts=receipt['tracking_counts'],
        tracking_preserved=True,scan_cooldown_preserved=True,maximum_actions=10,per_library_action_limit=5,
        permanent_deletion_authorized=False,media_read_only=False,root_filesystem_read_only=True,
        media_host_path=next(item['Source'] for item in current['Mounts'] if item['Destination']=='/media'),
        host_logs=host_logs,mount_count=2,published_ports=payload['HostConfig'].get('PortBindings',{}),
        template_filename=name,template_installed=False,deployment_authorized=False,service_changes_performed=False,
        writer_quiescence_verified=False,backup_freshness_verified=False,
        preparation_sha256=hashlib.sha256(files[COMPLETE]).hexdigest(),
        sha256={'proposed-container.json':hashlib.sha256(raw).hexdigest(),'proposed-template.xml':hashlib.sha256(xml).hexdigest()})
    fd=_private_root(Path(output),output_identity)
    try:
        if os.listdir(fd): raise RuntimeError('New empty review required')
        _write_private(fd,'proposed-container.json',raw); _write_private(fd,'proposed-template.xml',xml)
        if private_files(prepared,capture_identity=True)!=(files,identities) or load_backup_payloads(**selected)!=(payloads,receipt):
            raise RuntimeError('Review inputs changed')
        _write_private(fd,'review-complete.json',_encode(report))
    finally: os.close(fd)
    return report


def main():
    import argparse,sys
    parser=argparse.ArgumentParser(allow_abbrev=False)
    for name in ('backup-identity','fingerprint','output-identity','host-logs','reference'): parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    try:
        def identity(value):
            if not re.fullmatch(r'[0-9]+:[0-9]+',value): raise ValueError('Identity required')
            return tuple(map(int,value.split(':')))
        raw=sys.stdin.buffer.read(16*1024*1024+1)
        if len(raw)>16*1024*1024: raise ValueError('Bounded inspection required')
        values=parse_unique_json(raw)
        if len(values['containers'])!=1 or len(values['images'])!=1: raise ValueError('Single image and container required')
        fd=_open_directory('/templates')
        try:
            names=sorted(name for name in os.listdir(fd) if name.endswith('.xml'))
            if len(names)>256: raise ValueError('Bounded inventory required')
            templates=[(name,_local(fd,name)[0]) for name in names]
        finally: os.close(fd)
        result=review(backup='/backup',backup_identity=identity(args.backup_identity),fingerprint=args.fingerprint,
            prepared='/prepared',current=values['containers'][0],image=values['images'][0],templates=templates,
            host_logs=args.host_logs,reference=args.reference,output='/review',output_identity=identity(args.output_identity))
        print(json.dumps(result,sort_keys=True)); return 0
    except Exception as error:
        print(json.dumps(dict(status='json_cutover_review_blocked',error_type=type(error).__name__,
            deployment_authorized=False,service_changes_performed=False,partial_review_retained=True))); return 2

if __name__=='__main__': raise SystemExit(main())
