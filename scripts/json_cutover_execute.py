"""Fingerprint-bound JSON handoff. No automatic restoration or operation replay."""
from copy import deepcopy
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
from time import monotonic, sleep
from urllib.parse import quote

from app.sqlite_json import parse_unique_json
from app.sqlite_preview_install import _private_root
from app.sqlite_release_recovery import _local, _encode
from app.sqlite_scheduled_paths import _open_directory
from scripts.json_cutover_review import private_files, verify_prepared, metadata, COMPLETE
from scripts.sqlite_preview_service import NAME, LABEL, Docker, Journal, validate_original, container_id
from scripts.unraid_live_execute import validate_live_container
from scripts.unraid_live_update_backup import load_backup_payloads
from scripts.unraid_update_candidate_execute import SelectedUpdate, REVIEW_FILES, _capture
from scripts.unraid_update_candidate_handoff import handoff, recover


def sha(raw): return hashlib.sha256(raw).hexdigest()


def source_helper_payload(*, current, host_backup, host_checkout, backup_identity, fingerprint, request_id):
    """The old packaged validator reads its original mounts; no network/socket/writes."""
    for raw in (host_backup,host_checkout):
        path=Path(raw)
        if not path.is_absolute() or str(path)!=raw or '..' in path.parts or any(ord(c)<32 for c in raw):
            raise ValueError('Canonical helper binds required')
    mounts=current['Mounts']
    if len(mounts)!=3 or {row['Destination'] for row in mounts}!={'/media','/app/logs','/sqlite-control'}:
        raise ValueError('Exact old source binds required')
    if any(row.get('Type')!='bind' for row in mounts): raise ValueError('Old bind sources required')
    bindings=[dict(Type='bind',Source=row['Source'],Target=row['Destination'],ReadOnly=True,
                   BindOptions={'Propagation':'rprivate'}) for row in mounts]
    bindings.extend(dict(Type='bind',Source=source,Target=target,ReadOnly=True,BindOptions={'Propagation':'rprivate'})
                    for source,target in ((host_backup,'/backup'),(host_checkout,'/review-source')))
    normalized=deepcopy(current); normalized['Name']='/'+NAME
    code=('import io,os,sys; '
          'sys.stdin=io.TextIOWrapper(io.BytesIO(os.environ["JSON_CUTOVER_OBSERVATION"].encode())); '
          'from scripts.json_cutover_source_review import main; raise SystemExit(main())')
    return dict(Image=current['Image'],User='0:0',WorkingDir='/app',Entrypoint=['python','-B','-c',code],
        Cmd=['--backup-identity',str(backup_identity[0])+':'+str(backup_identity[1]),'--fingerprint',fingerprint],
        Env=['PYTHONPATH=/app:/app/app:/review-source','PYTHONDONTWRITEBYTECODE=1',
             'JSON_CUTOVER_OBSERVATION='+_encode([normalized]).decode()],
        Labels={'io.media-collection-auditor.json-source-check':request_id},Volumes=None,
        HostConfig=dict(NetworkMode='none',ReadonlyRootfs=True,Privileged=False,CapDrop=['ALL'],CapAdd=[],
            SecurityOpt=['no-new-privileges'],Mounts=bindings,Binds=None,RestartPolicy={'Name':'no'},
            PidsLimit=64,Memory=256*1024*1024,AutoRemove=False))


def complete_helper(engine, *, payload, label, request_id):
    identity=engine.create('auditor-json-check-'+request_id[:20],payload)
    def inspected():
        value=engine.inspect(identity)
        if (value.get('Id')!=identity or value.get('Image')!=payload['Image']
                or value.get('Config',{}).get('Labels',{}).get(label)!=request_id):
            raise RuntimeError('Source helper identity changed')
        return value
    inspected(); engine.start(identity)
    deadline=monotonic()+45
    while monotonic()<deadline:
        value=inspected(); state=value['State']
        if not state.get('Running'):
            if state.get('Status')!='exited' or state.get('ExitCode')!=0 or state.get('OOMKilled') or state.get('Error'):
                raise RuntimeError('Current source no longer matches backup; helper retained')
            # Remove only this exact, successfully exited disposable helper.
            engine.request('DELETE','/containers/'+quote(identity,safe=''),statuses=(204,))
            return
        sleep(.25)
    raise RuntimeError('Source helper deadline expired; helper retained')


def check_source(engine, *, current, host_backup, host_checkout, backup_identity, fingerprint):
    request_id=os.urandom(32).hex()
    payload=source_helper_payload(current=current,host_backup=host_backup,host_checkout=host_checkout,
        backup_identity=backup_identity,fingerprint=fingerprint,request_id=request_id)
    complete_helper(engine,payload=payload,label='io.media-collection-auditor.json-source-check',request_id=request_id)


def data_helper_payload(*, image_id, host_logs, target, expected_identity, expected_hashes, request_id):
    """Verify actual Docker-resolved logs, including before a stale recovery."""
    code='''import hashlib,json,os,stat,sys
expected=json.loads(sys.argv[1]); root=os.open('/app/logs',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try:
 info=os.fstat(root); assert [info.st_dev,info.st_ino]==expected['identity']
 for name,digest in expected['hashes'].items():
  fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=root)
  try:
   before=os.fstat(fd); assert stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size<=67108864
   data=bytearray()
   while len(data)<=67108864:
    chunk=os.read(fd,65536)
    if not chunk: break
    data.extend(chunk)
   after=os.fstat(fd); named=os.stat(name,dir_fd=root,follow_symlinks=False)
   key=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
   assert key(before)==key(after)==key(named) and hashlib.sha256(data).hexdigest()==digest
  finally: os.close(fd)
finally: os.close(root)
'''
    expected=dict(identity=list(expected_identity),hashes=expected_hashes)
    if set(expected_hashes)!={'auditor_state.json','auditor_config.json'}: raise ValueError('Exact prepared JSON files required')
    host=dict(NetworkMode='none',ReadonlyRootfs=True,Privileged=False,CapDrop=['ALL'],CapAdd=[],
        SecurityOpt=['no-new-privileges'],RestartPolicy={'Name':'no'},PidsLimit=64,Memory=256*1024*1024,AutoRemove=False)
    if target is not None:
        host['VolumesFrom']=[container_id(target)+':ro']
    else:
        path=Path(host_logs)
        if not path.is_absolute() or str(path)!=host_logs or '..' in path.parts: raise ValueError('Canonical prepared logs required')
        host['Mounts']=[dict(Type='bind',Source=host_logs,Target='/app/logs',ReadOnly=True,BindOptions={'Propagation':'rprivate'})]
    return dict(Image=image_id,User='0:0',WorkingDir='/app',Entrypoint=['python','-B','-c',code],
        Cmd=[_encode(expected).decode()],Env=['PYTHONDONTWRITEBYTECODE=1'],Volumes=None,
        Labels={'io.media-collection-auditor.json-data-check':request_id},HostConfig=host)


def check_data(engine, **kwargs):
    request_id=os.urandom(32).hex()
    complete_helper(engine,payload=data_helper_payload(**kwargs,request_id=request_id),
        label='io.media-collection-auditor.json-data-check',request_id=request_id)


def validate_json_container(live, *, identity, image_id, request_id, payload, running):
    # Reuse established mount/environment/security verification, normalizing only
    # the explicit -B entrypoint difference for that legacy validator.
    if live.get('Config',{}).get('Entrypoint')!=['python','-B','-m','app.main']:
        raise RuntimeError('Exact packaged JSON entrypoint required')
    normalized=deepcopy(live); normalized['Config']['Entrypoint']=['python','-m','app.main']
    validate_live_container(normalized,identity=identity,image_id=image_id,request_id=request_id,payload=payload,running=running)
    config=live['Config']; host=live['HostConfig']
    if (config.get('Image')!=payload['Image'] or config.get('Cmd') not in (None,[])
            or config.get('Volumes') not in (None,{}) or config.get('Healthcheck')
            or config.get('Labels')!=payload.get('Labels') or host.get('VolumesFrom')
            or len(live['Mounts'])!=2 or any(row.get('Type')!='bind' or row.get('Propagation','rprivate')!='rprivate' for row in live['Mounts'])
            or {row['Destination'] for row in live['Mounts']}!={'/media','/app/logs'}):
        raise RuntimeError('JSON replacement differs from exact reviewed layout')


def health_contract(summary, audit, counts):
    expected={name:counts[section] for name,section in
        (('waiting','first_seen'),('holding','queued'),('keep','keep_seen'),('removal','in_removal'),('arr_sync_pending','arr_sync_pending'))}
    if (summary.get('storage_authority')!='json' or summary.get('tracking_counts')!=expected
            or summary.get('pending_operation_present') is not False or summary.get('read_only') is not True
            or summary.get('freshness_verified') is not False
            or audit.get('storage_authority')!='json' or audit.get('worker_mode')!='json_serialized'
            or audit.get('execution_mode')!='scheduled_live_moves' or audit.get('execution_blocked') is not False
            or audit.get('running') is not False or audit.get('queued') is not False or not audit.get('next_run')
            or audit.get('maximum_actions')!=10 or audit.get('per_library_action_limit')!=5
            or audit.get('minimum_live_scan_interval_seconds')!=3600
            or audit.get('permanent_deletion_authorized') is not False):
        raise RuntimeError('JSON readiness or initial tracking parity unavailable')


def verify_json_health(*, engine, identity, env, counts):
    token=env.get('INTEGRATION_API_TOKEN'); port=int(env.get('WEB_PORT','8080'))
    if not token: raise RuntimeError('Existing API token required')
    deadline=monotonic()+30
    while monotonic()<deadline:
        current=engine.inspect(identity)
        if current.get('State',{}).get('Running') is not True: raise RuntimeError('JSON service exited before readiness')
        address=current.get('NetworkSettings',{}).get('Networks',{}).get('bridge',{}).get('IPAddress')
        try:
            parsed=ipaddress.ip_address(address)
            if parsed.version!=4 or not parsed.is_private or parsed.is_loopback or parsed.is_link_local:
                raise RuntimeError('Private bridge address required')
            def get(route, authenticated=False, parse=True):
                connection=http.client.HTTPConnection(str(parsed),port,timeout=2)
                try:
                    connection.request('GET',route,headers={'Authorization':'Bearer '+token} if authenticated else {})
                    response=connection.getresponse(); raw=response.read(1024*1024+1)
                    if len(raw)>1024*1024: raise RuntimeError('Bounded readiness response required')
                    return response.status,parse_unique_json(raw) if parse else None
                finally: connection.close()
            if get('/login',parse=False)[0]!=200: raise RuntimeError('Login unavailable')
            for route in ('/api/v1/summary','/api/v1/audit-status'):
                if get(route)[0]!=401: raise RuntimeError('API authentication boundary changed')
            code,summary=get('/api/v1/summary',True); status,audit=get('/api/v1/audit-status',True)
            if code!=200 or status!=200: raise RuntimeError('Authenticated JSON API unavailable')
            health_contract(summary,audit,counts)
            return
        except (OSError,ValueError,RuntimeError): sleep(.25)
    raise RuntimeError('JSON readiness deadline expired')


class SelectedJSON(SelectedUpdate):
    def __init__(self, *, engine, review, review_identity, review_fingerprint, backup, backup_identity,
                 backup_fingerprint, prepared, templates, host_backup, host_checkout, source_check=check_source,data_check=check_data):
        self.engine,self.review,self.templates=engine,Path(review),Path(templates)
        self.review_identity=review_identity
        fd=_private_root(self.review,review_identity); os.close(fd)
        self.files=_capture(self.review,REVIEW_FILES)
        if sha(self.files['review-complete.json'][0])!=review_fingerprint: raise RuntimeError('Selected review changed')
        self.report=parse_unique_json(self.files['review-complete.json'][0]); report=self.report
        if report.get('sha256')!={name:sha(self.files[name][0]) for name in REVIEW_FILES[1:]}:
            raise RuntimeError('Proposal changed')
        self.payload=parse_unique_json(self.files['proposed-container.json'][0]); self.xml=self.files['proposed-template.xml'][0]
        self.selected=dict(directory=Path(backup),expected_identity=backup_identity,expected_fingerprint=backup_fingerprint)
        self.data,self.backup_receipt=load_backup_payloads(**self.selected)
        self.captured=parse_unique_json(self.data['current.inspect.json']); self.image=engine.image(report['reference'])
        self.prepared=Path(prepared); self.prepared_files,self.prepared_identity=private_files(self.prepared,capture_identity=True)
        self.env,_=verify_prepared(files=self.prepared_files,payloads=self.data,receipt=self.backup_receipt,
            image=self.image,fingerprint=backup_fingerprint)
        if (report.get('status')!='json_cutover_review_prepared' or report.get('candidate_image_id')!=self.image['Id']
                or report.get('original_container_id')!=self.captured['Id'] or report.get('backup_fingerprint')!=backup_fingerprint
                or report.get('source_revision')!=self.image['Config']['Labels']['org.opencontainers.image.revision']
                or report.get('tracking_counts')!=self.backup_receipt['tracking_counts']
                or report.get('source_snapshot_revision')!=self.backup_receipt['snapshot_revision']
                or report.get('preparation_sha256')!=sha(self.prepared_files[COMPLETE])
                or report.get('maximum_actions')!=10 or report.get('per_library_action_limit')!=5
                or report.get('permanent_deletion_authorized') is not False):
            raise RuntimeError('Exact complete JSON cutover selection required')
        self.host_logs=report['host_logs']; self.host_backup,self.host_checkout=host_backup,host_checkout
        self.source_check,self.data_check=source_check,data_check
        self.original_templates=self.inventory()
        matches=[name for name,raw in self.original_templates if raw in (self.data['current-template.xml'],self.xml)]
        if len(matches)!=1 or matches[0]!=report['template_filename']: raise RuntimeError('Unique unchanged managed template required')
        self.template_name=matches[0]

    def check_replacement_data(self, target=None):
        self.data_check(self.engine,image_id=self.image['Id'],host_logs=self.host_logs,target=target,
            expected_identity=self.prepared_identity['logs'],
            expected_hashes={name:sha(self.prepared_files['logs/'+name]) for name in ('auditor_state.json','auditor_config.json')})

    def validate(self, *, recovery=False):
        self.diagnostic_stage='pinned_inputs'
        fd=_private_root(self.review,self.review_identity); os.close(fd)
        if (_capture(self.review,REVIEW_FILES)!=self.files
                or load_backup_payloads(**self.selected)!=(self.data,self.backup_receipt)
                or private_files(self.prepared,capture_identity=True)!=(self.prepared_files,self.prepared_identity)
                or self.engine.image(self.report['reference'])!=self.image):
            raise RuntimeError('Selected inputs changed; no stale state adoption')
        self.diagnostic_stage='original_container'
        observed=self.engine.inspect(self.captured['Id'])
        allowed=(NAME,NAME+'_before_update_'+self.captured['Id'][:12]) if recovery else (NAME,)
        if observed['Name'][1:] not in allowed or (recovery and observed['State']['Running'] is not False):
            raise RuntimeError('Original role changed')
        validate_original(observed,self.captured,name=observed['Name'][1:],running=observed['State']['Running'])
        self.diagnostic_stage='template_and_proposal'
        inventory=self.template_check(recovery=recovery)
        from app.unraid_update_review import matching_templates
        if len(matching_templates(inventory))!=1: raise RuntimeError('Ambiguous template inventory')
        payload,xml=metadata(current=self.captured,image=self.image,template=self.data['current-template.xml'],
            environment=self.env,host_logs=self.host_logs,reference=self.report['reference'],attempt=self.payload['Labels'][LABEL])
        if payload!=self.payload or xml!=self.xml: raise RuntimeError('Proposal cannot be reconstructed')
        self.diagnostic_stage='prepared_host_binding'
        self.check_replacement_data()
        self.diagnostic_stage='current_source_validation'
        self.source_check(self.engine,current=observed,host_backup=self.host_backup,host_checkout=self.host_checkout,
            backup_identity=self.selected['expected_identity'],fingerprint=self.selected['expected_fingerprint'])
        self.diagnostic_stage='final_input_recheck'
        validate_original(self.engine.inspect(self.captured['Id']),self.captured,
            name=observed['Name'][1:],running=observed['State']['Running'])
        if (_capture(self.review,REVIEW_FILES)!=self.files or self.inventory()!=self.original_templates
                or private_files(self.prepared,capture_identity=True)!=(self.prepared_files,self.prepared_identity)
                or load_backup_payloads(**self.selected)!=(self.data,self.backup_receipt)):
            raise RuntimeError('Inputs changed during source validation')


def run_selected(update, *, action, parent, reviewed_new_id=None, health=verify_json_health):
    if action=='check':
        if (update.engine.inspect(update.captured['Id'])['State']['Running'] is not True
                or os.path.lexists(update.review/'service-request.json')):
            raise RuntimeError('Interrupted handoff requires explicit recovery')
        update.validate()
        return dict(status='json_handoff_preflight_verified',reference=update.report['reference'],maximum_actions=10,
            per_library_action_limit=5,permanent_deletion_authorized=False,service_changes_performed=False,
            media_actions_authorized=False,template_installed=False)
    from app.sqlite_lock import _exclusive_lock
    with _exclusive_lock(update.review/'.handoff.lock','JSON handoff already active'):
        def replacement_check(live,**kwargs):
            update.diagnostic_stage='replacement_binding'
            validate_json_container(live,**kwargs)
            update.check_replacement_data(live['Id'])
        common=dict(engine=update.engine,captured=update.captured,payload=update.payload,image_id=update.image['Id'],
                    validator=replacement_check)
        if action=='deploy':
            def readiness(identity):
                update.diagnostic_stage='json_readiness'
                health(engine=update.engine,identity=identity,env=update.env,counts=update.report['tracking_counts'])
            def install():
                update.diagnostic_stage='template_install'
                update.install()
            result=handoff(**common,journal=Journal(parent),precheck=update.validate,install=install,live_canary=True,
                health=readiness)
            result.update(status='json_worker_cutover_complete',storage_authority='json',media_actions_authorized=True,
                maximum_actions=10,per_library_action_limit=5,permanent_deletion_authorized=False)
            return result
        if action!='recover': raise ValueError('Known action required')
        from scripts.sqlite_preview_service import verify_http_health
        old_env=dict(value.split('=',1) for value in update.captured['Config']['Env'])
        result=recover(**common,journal=Journal(parent,'recovery'),new_id=update.recovery_id(reviewed_new_id),
            precheck=lambda:update.validate(recovery=True),restore_template=lambda:update.install(restore=True),
            health=lambda identity:verify_http_health(engine=update.engine,identity=identity,env=old_env,live_canary=True))
        result['status']='unchanged_json_cutover_previous_recovered'
        return result


def main():
    import argparse
    parser=argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('action',choices=('check','deploy','recover'))
    for key in ('review-identity','review-fingerprint','backup-identity','backup-fingerprint','daemon-id','host-backup','host-checkout'):
        parser.add_argument('--'+key,required=True)
    parser.add_argument('--reviewed-new-id')
    args=parser.parse_args()
    update=None
    try:
        def identity(raw):
            if not re.fullmatch(r'[0-9]+:[0-9]+',raw): raise ValueError('Directory identity required')
            return tuple(map(int,raw.split(':')))
        update=SelectedJSON(engine=Docker(endpoint='/var/run/docker.sock',expected_daemon=args.daemon_id),
            review='/review',review_identity=identity(args.review_identity),review_fingerprint=args.review_fingerprint,
            backup='/backup',backup_identity=identity(args.backup_identity),backup_fingerprint=args.backup_fingerprint,
            prepared='/prepared',templates='/templates',host_backup=args.host_backup,host_checkout=args.host_checkout)
        fd=_open_directory('/review')
        try: result=run_selected(update,action=args.action,parent=fd,reviewed_new_id=args.reviewed_new_id)
        finally: os.close(fd)
    except Exception as error:
        print(json.dumps(dict(status='json_handoff_stopped_for_review',error_type=type(error).__name__,
            diagnostic_stage=getattr(update,'diagnostic_stage','selected_inputs'),
            automatic_restoration=False,media_actions_authorized=False,permanent_deletion_authorized=False))); return 2
    print(json.dumps(result,sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
