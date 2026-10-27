"""Prepare a same-image stopped-preview recovery; never control a service."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from html import unescape

from app.sqlite_disposable_restore import _write_private
from app.sqlite_preview_install import _private_root
from app.sqlite_release_recovery import _encode
from scripts.unraid_update_backup import load_backup_payloads
from scripts.unraid_update_prepare import prepare_replacement

REFERENCE = re.compile(r'ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}')


def replacement_metadata(*, current, image, template, environment, reference, host_logs, host_control, attempt):
    if (current.get('Name') != '/media_collection_auditor' or current.get('State',{}).get('Running') is not False
            or image.get('Id') != current.get('Image') or not REFERENCE.fullmatch(reference)
            or reference != current['Config'].get('Image') or reference not in (image.get('RepoDigests') or [])):
        raise ValueError('Stopped same-image immutable recovery required')
    if b'<!DOCTYPE' in template.upper() or b'<!ENTITY' in template.upper():
        raise ValueError('Plain managed template required')
    root = ET.fromstring(template)
    if root.tag != 'Container' or len(root.findall('Name')) != 1 or root.findtext('Name') != 'media_collection_auditor':
        raise ValueError('Single matching managed template required')
    if len(root.findall('Repository')) != 1 or root.findtext('Repository') != reference:
        raise ValueError('Matching saved image required')
    mounts = {item['Destination']:deepcopy(item) for item in current['Mounts']}
    if set(mounts) != {'/media','/app/logs','/sqlite-control'} or len(current['Mounts']) != 3:
        raise ValueError('Exact three bind roots required')
    if any(item.get('Type') != 'bind' for item in mounts.values()) or mounts['/media'].get('RW') is not False:
        raise ValueError('Read-only media bind required')
    destinations = {'/app/logs':host_logs, '/sqlite-control':host_control}
    for value in destinations.values():
        path=Path(value)
        if not path.is_absolute() or str(path) != value or '..' in path.parts or any(c in value for c in ',\n\r'):
            raise ValueError('Canonical new host directories required')
        for item in mounts.values():
            old=Path(item['Source'])
            if path==old or path in old.parents or old in path.parents:
                raise ValueError('Replacement must not overlap old roots')
    if host_logs==host_control or Path(host_logs) in Path(host_control).parents or Path(host_control) in Path(host_logs).parents:
        raise ValueError('Disjoint replacement roots required')
    for target,value in destinations.items(): mounts[target]['Source']=value
    seen=set()
    for item in list(root.findall('Config')):
        key=(item.get('Type'),item.get('Target'))
        if key in seen: raise ValueError('Duplicate template configuration')
        seen.add(key)
        if key[0]=='Path':
            if key[1] not in mounts: raise ValueError('Unknown template bind')
            value=mounts[key[1]]['Source']; item.text=value; item.set('Default',value)
        if key[0]=='Variable':
            if key[1] not in environment:
                from app.sqlite_preview_template import RUNTIME_DEFAULTS
                if key[1] in RUNTIME_DEFAULTS: root.remove(item); continue
                raise ValueError('Unrepresented template variable')
            value=environment[key[1]]
            if unescape(value)!=value or '<' in value or '>' in value:
                raise ValueError('Lossless template variable required')
            item.text=value; item.set('Default',value)
    for key,value in sorted(environment.items()):
        if ('Variable',key) in seen: continue
        if unescape(value)!=value or '<' in value or '>' in value: raise ValueError('Lossless variable required')
        item=ET.SubElement(root,'Config',Type='Variable',Target=key,Name=key,Mode='',Display='advanced',Required='false',Mask='true',Default=value)
        item.text=value
    if {key[1] for key in seen if key[0]=='Path'} != set(mounts): raise ValueError('Complete template paths required')
    payload=deepcopy(current['Config']); host=deepcopy(current['HostConfig'])
    if host.get('ReadonlyRootfs') is not True or host.get('Privileged') is not False or host.get('RestartPolicy',{}).get('Name')!='no':
        raise ValueError('Read-only non-restarting preview required')
    if host.get('NetworkMode')!='bridge' or host.get('VolumesFrom') or current['Config'].get('Healthcheck'):
        raise ValueError('Ordinary bridge preview required')
    runtime=dict(item.split('=',1) for item in image['Config'].get('Env',[])); runtime.update(environment)
    payload.update(Image=reference,User='0:0',WorkingDir='/app',Entrypoint=['python','-m','app.main'],Cmd=None,StopSignal='SIGINT',Volumes=None,
                   Env=[key+'='+value for key,value in sorted(runtime.items())])
    from scripts.sqlite_preview_service import LABEL
    payload['Labels']={**payload.get('Labels',{}),LABEL:attempt}
    host['Binds']=None
    host['Mounts']=[{'Type':'bind','Source':item['Source'],'Target':target,'ReadOnly':target=='/media',
                     'BindOptions':{'Propagation':item.get('Propagation','rprivate')}} for target,item in sorted(mounts.items())]
    payload['HostConfig']=host
    return payload, ET.tostring(root,encoding='utf-8',xml_declaration=True)+b'\n'


def prepare(*, backup, backup_identity, fingerprint, logs_identity, control_identity, host_logs, host_control, image, reference):
    selected=dict(directory=backup,expected_identity=backup_identity,expected_fingerprint=fingerprint)
    data=load_backup_payloads(**selected); current=json.loads(data['current.inspect.json'])
    # Construct metadata before the first destination write, then bind actual new roots.
    env=dict(item.split('=',1) for item in current['Config']['Env'])
    from app.sqlite_preview_template import RUNTIME_DEFAULTS
    env={key:value for key,value in env.items() if key not in RUNTIME_DEFAULTS}
    env.update(STATE_FILE='/app/logs/auditor_state.json',WEB_CONFIG_FILE='/app/logs/auditor_config.json',SQLITE_STATE_FILE='/sqlite-control/release/state.db')
    attempt=os.urandom(32).hex()
    payload,xml=replacement_metadata(current=current,image=image,template=data['current-template.xml'],environment=env,
        reference=reference,host_logs=host_logs,host_control=host_control,attempt=attempt)
    report=prepare_replacement(backup=backup,backup_identity=backup_identity,backup_fingerprint=fingerprint,
        logs='/app/logs',logs_identity=logs_identity,control='/sqlite-control',control_identity=control_identity,candidate_image=image)
    result={'schema_version':1,'status':'same_image_replacement_prepared','original_container_id':current['Id'],
        'image_id':image['Id'],'reference':reference,'source_revision':report['source_revision'],
        'backup_fingerprint':fingerprint,'attempt':attempt,'host_logs':host_logs,'host_control':host_control,
        'sha256':{'create-payload.json':hashlib.sha256(_encode(payload)).hexdigest(),
                  'replacement-template.xml':hashlib.sha256(xml).hexdigest()},
        'original_template_sha256':hashlib.sha256(data['current-template.xml']).hexdigest(),
        'original_inspect_sha256':hashlib.sha256(data['current.inspect.json']).hexdigest(),
        'media_actions_authorized':False,'service_changes_performed':False,'update_authorized':False}
    fd=_private_root(Path('/app/logs'),logs_identity)
    try:
        _write_private(fd,'create-payload.json',_encode(payload)); _write_private(fd,'replacement-template.xml',xml)
        _write_private(fd,'update-selection.json',_encode(result))
    finally: os.close(fd)
    return {key:value for key,value in result.items() if key not in ('sha256','attempt','original_template_sha256','original_inspect_sha256')}|{
        'selection_fingerprint':hashlib.sha256(_encode(result)).hexdigest(),
        'enable_tv_effective':str(json.loads(data['saved-config.json']).get('ENABLE_TV',env.get('ENABLE_TV','false'))).lower()=='true'}


def main():
    import argparse,sys
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    for key in ('backup','backup-identity','fingerprint','logs-identity','control-identity','host-logs','host-control','reference'):
        parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    def identity(raw):
        if not re.fullmatch('[0-9]+:[0-9]+',raw): raise ValueError('Expected directory identity')
        return tuple(map(int,raw.split(':')))
    try:
        raw=sys.stdin.buffer.read(16*1024*1024+1)
        if len(raw)>16*1024*1024: raise ValueError('Bounded image input')
        from app.sqlite_json import parse_unique_json
        images=parse_unique_json(raw)
        if len(images)!=1: raise ValueError('Single cached image')
        result=prepare(backup=args.backup,backup_identity=identity(args.backup_identity),fingerprint=args.fingerprint,
            logs_identity=identity(args.logs_identity),control_identity=identity(args.control_identity),
            host_logs=args.host_logs,host_control=args.host_control,image=images[0],reference=args.reference)
    except Exception as error:
        print(json.dumps({'status':'replacement_preparation_blocked','error_type':type(error).__name__,
            'service_changes_performed':False,'partial_files_retained':True})); return 2
    print(json.dumps(result,sort_keys=True)); return 0


if __name__=='__main__': raise SystemExit(main())
