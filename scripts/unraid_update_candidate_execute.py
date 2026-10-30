"""Explicit reviewed preview handoff adapter. Check mode makes no service changes."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import tempfile
from xml.etree import ElementTree as ET
from app.sqlite_json import parse_unique_json
from app.sqlite_release_recovery import _encode,_local
from app.sqlite_preview_install import _private_root,_replace_config
from app.sqlite_scheduled_paths import _open_directory
from scripts.unraid_update_candidate_review import review_candidate,_capture,_environment
from scripts.unraid_update_backup import load_backup_payloads
from scripts.unraid_update_production_prepare import candidate_review_metadata
from scripts.sqlite_preview_service import NAME,LABEL,Journal,validate_original,verify_http_health,Docker
from scripts.unraid_update_candidate_handoff import handoff,recover

REVIEW_FILES=('review-complete.json','proposed-container.json','proposed-template.xml')
PHASES=('original_stop_requested','original_stopped','original_archive_requested','original_archived',
    'replacement_create_requested','replacement_created','replacement_start_requested','replacement_started',
    'replacement_health_verified','template_install_requested','update_complete')


def sha(raw):return hashlib.sha256(raw).hexdigest()


class SelectedUpdate:
    REVIEW_STATUS = "candidate_review_prepared"

    @staticmethod
    def load_backup(**selected):
        return load_backup_payloads(**selected)
    def __init__(self,*,engine,review,review_identity,review_fingerprint,backup,backup_identity,
                 backup_fingerprint,logs,control,old_logs,old_control,templates):
        self.engine,self.review,self.templates=engine,Path(review),Path(templates)
        fd=_private_root(self.review,review_identity);os.close(fd)
        self.files=_capture(self.review,REVIEW_FILES)
        if sha(self.files['review-complete.json'][0])!=review_fingerprint:raise RuntimeError('Review changed')
        self.report=parse_unique_json(self.files['review-complete.json'][0]);r=self.report
        for name in REVIEW_FILES[1:]:
            if sha(self.files[name][0])!=r['sha256'][name]:raise RuntimeError('Proposal changed')
        self.payload=parse_unique_json(self.files['proposed-container.json'][0]);self.xml=self.files['proposed-template.xml'][0]
        self.selected=dict(directory=Path(backup),expected_identity=backup_identity,expected_fingerprint=backup_fingerprint)
        self.data=self.load_backup(**self.selected);self.captured=parse_unique_json(self.data['current.inspect.json'])
        self.image=engine.image(r['reference'])
        if (r.get('status')!=self.REVIEW_STATUS or r.get('image_reference_status')!='verified_cached_digest'
                or r.get('backup_fingerprint')!=backup_fingerprint or r.get('candidate_image_id')!=self.image['Id']
                or r.get('original_container_id')!=self.captured['Id'] or self.payload['Image']!=r['reference']):
            raise RuntimeError('Exact published review required')
        mounts={item['Target']:item['Source'] for item in self.payload['HostConfig']['Mounts']}
        self.host_logs,self.host_control=mounts['/app/logs'],mounts['/sqlite-control']
        self.env=_environment(_capture(Path(logs),('runtime.env',))['runtime.env'][0])
        self.review_args=dict(backup=Path(backup),backup_identity=backup_identity,fingerprint=backup_fingerprint,
            logs=Path(logs),control=Path(control),old_logs=Path(old_logs),old_control=Path(old_control),
            image=self.image,host_logs=self.host_logs,host_control=self.host_control,reference=r['reference'])
        self.original_templates=self.inventory()
        matches=[name for name,raw in self.original_templates if raw in (self.data['current-template.xml'],self.xml)]
        if len(matches)!=1:raise RuntimeError('One unchanged managed template required')
        self.template_name=matches[0]

    def inventory(self):
        fd=_open_directory(str(self.templates))
        try:
            names=sorted(name for name in os.listdir(fd) if name.endswith('.xml'))
            if len(names)>256:raise RuntimeError('Bounded templates required')
            return [(name,_local(fd,name)[0]) for name in names]
        finally:os.close(fd)

    def template_check(self,*,recovery=False):
        current=self.inventory()
        if current!=self.original_templates:raise RuntimeError('Template inventory changed')
        raw=dict(current)[self.template_name]
        allowed=(self.data['current-template.xml'],self.xml) if recovery else (self.data['current-template.xml'],)
        if raw not in allowed:raise RuntimeError('Managed template changed')
        return [(name,self.data['current-template.xml'] if name==self.template_name else value) for name,value in current]

    def validate(self,*,recovery=False):
        if _capture(self.review,REVIEW_FILES)!=self.files or self.load_backup(**self.selected)!=self.data:
            raise RuntimeError('Pinned review or backup changed')
        image=self.engine.image(self.report['reference'])
        if image!=self.image:raise RuntimeError('Cached image selection changed')
        observed=self.engine.inspect(self.captured['Id'])
        allowed=(NAME,NAME+'_before_update_'+self.captured['Id'][:12]) if recovery else (NAME,)
        if observed['Name'][1:] not in allowed:raise RuntimeError('Original role changed')
        running=observed['State']['Running']
        if recovery and running is not False:raise RuntimeError('Recovery requires stopped original')
        validate_original(observed,self.captured,name=observed['Name'][1:],running=running)
        normalized=deepcopy(observed);normalized['Name']='/'+NAME;normalized['State']['Running']=self.captured['State']['Running']
        inventory=self.template_check(recovery=recovery)
        with tempfile.TemporaryDirectory(prefix='candidate-offline-check-') as temporary:
            output=Path(temporary);output.chmod(0o700);info=output.stat()
            fresh=review_candidate(**self.review_args,live=normalized,templates=lambda:inventory,
                output=output,output_identity=(info.st_dev,info.st_ino))
        if fresh['tracking_counts']!=self.report['tracking_counts']:raise RuntimeError('Tracking changed')
        payload,xml=candidate_review_metadata(current=normalized,image=self.image,template=self.data['current-template.xml'],
            environment=self.env,host_logs=self.host_logs,host_control=self.host_control,attempt=self.payload['Labels'][LABEL])
        payload['Image']=self.report['reference'];root=ET.fromstring(xml);root.find('Repository').text=self.report['reference']
        xml=ET.tostring(root,encoding='utf-8',xml_declaration=True)+b'\n'
        if payload!=self.payload or xml!=self.xml:raise RuntimeError('Proposal reconstruction changed')
        if _capture(self.review,REVIEW_FILES)!=self.files or self.inventory()!=self.original_templates:
            raise RuntimeError('Inputs changed during validation')

    def install(self,*,restore=False):
        self.template_check(recovery=restore)
        desired=self.data['current-template.xml'] if restore else self.xml
        fd=_open_directory(str(self.templates))
        try:
            raw,info=_local(fd,self.template_name)
            if raw!=desired:_replace_config(fd,self.template_name,raw,info,desired)
        finally:os.close(fd)
        expected=[(name,desired if name==self.template_name else value) for name,value in self.original_templates]
        if self.inventory()!=expected:raise RuntimeError('Template installation acknowledgement uncertain')

    def recovery_id(self,reviewed_new_id=None):
        fd=_open_directory(str(self.review))
        try:
            raw=_local(fd,'service-request.json')[0];request=parse_unique_json(raw)
            if (request.get('original_container_id')!=self.captured['Id']
                    or request.get('candidate_image_id')!=self.image['Id']
                    or request.get('attempt')!=self.payload['Labels'][LABEL]):raise RuntimeError('Handoff request changed')
            previous=sha(raw);new=None;phases=[]
            names=sorted(name for name in os.listdir(fd) if re.fullmatch(r'service-[0-9]{4}\.json',name))
            if not names or len(names)>len(PHASES):raise RuntimeError('Known handoff journal required')
            for number,name in enumerate(names,1):
                raw=_local(fd,name)[0];event=parse_unique_json(raw)
                if (name!='service-%04d.json'%number or event.get('sequence')!=number
                        or event.get('previous_sha256')!=previous or event.get('phase')!=PHASES[number-1]):
                    raise RuntimeError('Handoff journal changed')
                if event['phase']=='replacement_created':new=event.get('container_id')
                if 'container_id' in event and event['container_id']!=new:raise RuntimeError('Replacement identity changed')
                phases.append(event['phase']);previous=sha(raw)
            if reviewed_new_id:
                if new and new!=reviewed_new_id:raise RuntimeError('Reviewed replacement differs')
                new=reviewed_new_id
            if 'replacement_create_requested' in phases and new is None:
                raise RuntimeError('Uncertain create needs explicit exact replacement ID')
            return new
        finally:os.close(fd)


def run_selected(update,*,action,parent,reviewed_new_id=None):
    if action=='check':
        update.validate()
        return {'status':'candidate_handoff_preflight_verified','service_changes_performed':False,
            'template_installed':False,'media_actions_authorized':False,'reference':update.report['reference']}
    from app.sqlite_lock import _exclusive_lock
    with _exclusive_lock(update.review/'.handoff.lock','Handoff/recovery already active'):
        if action=='deploy':
            return handoff(engine=update.engine,journal=Journal(parent),captured=update.captured,payload=update.payload,
                image_id=update.image['Id'],precheck=update.validate,install=update.install,
                health=lambda identity:verify_http_health(engine=update.engine,identity=identity,env=update.env))
        if action!='recover':raise ValueError('Known action required')
        new=update.recovery_id(reviewed_new_id)
        old_env=dict(item.split('=',1) for item in update.captured['Config']['Env'])
        return recover(engine=update.engine,journal=Journal(parent,'recovery'),captured=update.captured,
            payload=update.payload,image_id=update.image['Id'],new_id=new,
            precheck=lambda:update.validate(recovery=True),restore_template=lambda:update.install(restore=True),
            health=lambda identity:verify_http_health(engine=update.engine,identity=identity,env=old_env))


def main():
    import argparse,json
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('action',choices=('check','deploy','recover'))
    for key in ('review-identity','review-fingerprint','backup-identity','backup-fingerprint','daemon-id'):
        parser.add_argument('--'+key,required=True)
    parser.add_argument('--reviewed-new-id')
    args=parser.parse_args()
    def identity(raw):
        if not re.fullmatch(r'[0-9]+:[0-9]+',raw):raise ValueError('Directory identity required')
        return tuple(map(int,raw.split(':')))
    try:
        update=SelectedUpdate(engine=Docker(endpoint='/var/run/docker.sock',expected_daemon=args.daemon_id),
            review=Path('/review'),review_identity=identity(args.review_identity),review_fingerprint=args.review_fingerprint,
            backup=Path('/backup'),backup_identity=identity(args.backup_identity),backup_fingerprint=args.backup_fingerprint,
            logs=Path('/app/logs'),control=Path('/sqlite-control'),old_logs=Path('/old-logs'),old_control=Path('/old-control'),templates=Path('/templates'))
        fd=_open_directory('/review')
        try:result=run_selected(update,action=args.action,parent=fd,reviewed_new_id=args.reviewed_new_id)
        finally:os.close(fd)
    except Exception as error:
        print(json.dumps({'status':'candidate_handoff_stopped_for_review','error_type':type(error).__name__,
            'automatic_restoration':False,'media_actions_authorized':False}));return 2
    print(json.dumps(result,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
