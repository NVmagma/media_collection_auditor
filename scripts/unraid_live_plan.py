"""Pure live-canary container/template proposal. Never install or start anything."""
from html import unescape
from pathlib import PurePosixPath
import re
import shlex
from xml.etree import ElementTree as ET
from app.unraid_update_review import review_update
from app.sqlite_live_policy import validate_initial_live_policy
from scripts.unraid_update_production_prepare import _metadata,REFERENCE
from scripts.sqlite_preview_service import LABEL


def live_metadata(*,current,image,template,environment,reference,host_logs,host_control,host_media,attempt,effective_settings=None,diagnostic=None):
    def stage(name):
        if diagnostic is not None:diagnostic('proposal_'+name)
    stage('image_contract')
    labels=(image.get('Config') or {}).get('Labels') or {}
    config=image.get('Config') or {}
    if (not REFERENCE.fullmatch(reference or '') or reference not in (image.get('RepoDigests') or [])
            or not re.fullmatch(r'sha256:[0-9a-f]{64}',image.get('Id','')) or image.get('Id')==current.get('Image')
            or labels.get('io.media-collection-auditor.sqlite-activation')!='scheduled-moves'
            or not re.fullmatch(r'[0-9a-f]{40}',labels.get('org.opencontainers.image.revision',''))
            or config.get('Entrypoint')!=['python','-m','app.main'] or config.get('Cmd') not in (None,[])
            or config.get('StopSignal')!='SIGINT' or config.get('Volumes') not in (None,{})
            or not re.fullmatch(r'[0-9a-f]{64}',attempt or '')):
        raise ValueError('Exact published live canary and attempt required')
    stage('current_template')
    review=review_update(templates=[('current.xml',template)],container=current)
    if review['blockers'] or current.get('State',{}).get('Running') is not True:
        raise ValueError('Matching running preview required')
    stage('effective_policy')
    validate_initial_live_policy(environment if effective_settings is None else effective_settings)
    stage('native_path')
    media=PurePosixPath(host_media)
    if (not media.is_absolute() or str(media)!=host_media or '..' in media.parts
            or any(ord(c)<=32 or ord(c)==127 for c in host_media) or ',' in host_media
            or unescape(host_media)!=host_media or '<' in host_media or '>' in host_media):
        raise ValueError('Canonical explicitly reviewed native media root required')
    paths=[PurePosixPath(host_logs),PurePosixPath(host_control)]
    paths.extend(PurePosixPath(item['Source']) for item in current['Mounts'])
    if any(media==path or media in path.parents or path in media.parents for path in paths):
        raise ValueError('Native view must be distinct from old binds and private controls')
    stage('preserved_metadata')
    payload,xml=_metadata(current=current,image=image,template=template,environment=environment,
        reference=reference,host_logs=host_logs,host_control=host_control,attempt=attempt)
    host=payload['HostConfig']
    stage('capability_policy')
    if (host.get('CapAdd') not in (None,[])
            or host.get('Devices') not in (None,[]) or host.get('DeviceRequests') not in (None,[]) ):
        raise ValueError('Unprivileged capability-dropped canary required')
    # Explicitly approved live policy: private controls remain root-owned,
    # while Unraid media may be 99:100 and 0755. No chown/chmod is performed.
    host['CapDrop']=['ALL'];host['CapAdd']=['DAC_OVERRIDE']
    host['SecurityOpt']=list(host.get('SecurityOpt') or [])
    if any(value not in ('no-new-privileges','no-new-privileges:true','label=disable') for value in host['SecurityOpt']):
        raise ValueError('Reviewed container security options required')
    if not any(value.startswith('no-new-privileges') for value in host['SecurityOpt']):
        host['SecurityOpt'].append('no-new-privileges')
    mount=next(item for item in host['Mounts'] if item['Target']=='/media')
    mount.update(Source=host_media,ReadOnly=False,BindOptions={'Propagation':'rprivate'})
    custom={key:value for key,value in payload.get('Labels',{}).items()
            if not key.startswith(('org.opencontainers.image.','io.media-collection-auditor.'))}
    webui='http://[IP]:[PORT:'+environment.get('WEB_PORT','8080')+']/'
    payload['Labels']={**labels,**custom,LABEL:attempt,'net.unraid.docker.webui':webui}
    stage('labels')
    root=ET.fromstring(xml)
    field=root.find('ExtraParams')
    if field is None:field=ET.SubElement(root,'ExtraParams')
    args=shlex.split(field.text or '')
    normalized=[];index=0
    replaced=('--cap-drop','--cap-add','--security-opt','--user','--restart')
    allowed=('--pull=','--tmpfs=','--hostname=','--domainname=','--memory=','--memory-swap=',
             '--memory-reservation=','--pids-limit=','--cpu-shares=','--cpu-period=','--cpu-quota=',
             '--cpus=','--cpuset-cpus=','--memory-swappiness=','--cgroupns=','--dns=','--dns-option=',
             '--dns-search=','--add-host=','--log-driver=','--log-opt=')
    while index<len(args):
        value=args[index]
        if value in replaced:
            if index+1>=len(args):raise ValueError('Complete reviewed runtime argument required')
            index+=2;continue
        if any(value.startswith(flag+'=') for flag in replaced) or value=='--read-only':
            index+=1;continue
        if not value.startswith(allowed):raise ValueError('Unsupported template runtime argument')
        normalized.append(value);index+=1
    normalized.extend(('--read-only','--user=0:0','--restart=no','--cap-drop=ALL','--cap-add=DAC_OVERRIDE'))
    normalized.extend('--security-opt='+value for value in host['SecurityOpt'])
    field.text=shlex.join(normalized)
    item=root.find("Config[@Type='Path'][@Target='/media']")
    item.text=host_media;item.set('Default',host_media);item.set('Mode','rw')
    field=root.find('WebUI')
    if field is None:field=ET.SubElement(root,'WebUI')
    field.text=webui
    for item in list(root.findall('Config')):
        if item.get('Type')=='Label':root.remove(item)
    for key,value in sorted(payload['Labels'].items()):
        if not isinstance(value,str) or unescape(value)!=value or '<' in value or '>' in value:
            raise ValueError('Lossless live labels required')
        item=ET.SubElement(root,'Config',Type='Label',Target=key,Name=key,Mode='',Display='advanced',Required='false',Mask='false',Default=value)
        item.text=value
    return payload,ET.tostring(root,encoding='utf-8',xml_declaration=True)+b'\n'
