"""Explicit fingerprint-bound live canary handoff; never automatically restore."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
from scripts.unraid_update_candidate_execute import SelectedUpdate, REVIEW_FILES, _capture
from scripts.unraid_update_backup import load_backup_payloads
from scripts.unraid_live_review import review_live_candidate
from scripts.unraid_live_plan import live_metadata
from scripts.sqlite_preview_service import (NAME, LABEL, Journal, Docker, validate_original,
    validate_preview, verify_http_health)
from scripts.unraid_update_candidate_handoff import handoff, recover
from app.sqlite_live_binding import validate_live_binding
from app.sqlite_scheduled_paths import _open_directory


def validate_live_container(live, **kwargs):
    validate_preview(live, **kwargs)
    host=live.get('HostConfig', {})
    security=host.get('SecurityOpt') or []
    if (host.get('CapDrop') != ['ALL'] or host.get('CapAdd') not in (['DAC_OVERRIDE'], ['CAP_DAC_OVERRIDE'])
            or host.get('Devices') not in (None, []) or host.get('DeviceRequests') not in (None, [])
            or not any(value in ('no-new-privileges', 'no-new-privileges:true') for value in security)
            or any(value not in ('no-new-privileges', 'no-new-privileges:true', 'label=disable') for value in security)):
        raise RuntimeError('Live container security differs from approved policy')


class SelectedLive(SelectedUpdate):
    REVIEW_STATUS='live_cutover_review_prepared'
    LIVE_UPDATE=False

    def __init__(self, *, shared_media=Path('/shared-media'), native_media=Path('/media'), **kwargs):
        super().__init__(**kwargs)
        self.shared_media,self.native_media=shared_media,native_media

    def validate(self, *, recovery=False):
        if _capture(self.review, REVIEW_FILES)!=self.files or self.load_backup(**self.selected)!=self.data:
            raise RuntimeError('Pinned review or backup changed')
        if self.engine.image(self.report['reference'])!=self.image:
            raise RuntimeError('Cached image changed')
        observed=self.engine.inspect(self.captured['Id'])
        allowed=(NAME, NAME+'_before_update_'+self.captured['Id'][:12]) if recovery else (NAME,)
        if observed['Name'][1:] not in allowed or (recovery and observed['State']['Running'] is not False):
            raise RuntimeError('Original role changed')
        validate_original(observed,self.captured,name=observed['Name'][1:],running=observed['State']['Running'])
        normalized=deepcopy(observed)
        normalized['Name']='/'+NAME
        normalized['State']['Running']=self.captured['State']['Running']
        inventory=self.template_check(recovery=recovery)
        host_media=self.report['native_media_host_path']
        # Full review requires revision zero and exact logical backup equality.
        # Thus an advanced live database or retained intent cannot restore stale preview tracking.
        with tempfile.TemporaryDirectory(prefix='live-offline-check-') as temporary:
            output=Path(temporary);output.chmod(0o700);info=output.stat()
            fresh=review_live_candidate(**self.review_args,live=normalized,templates=lambda:inventory,
                output=output,output_identity=(info.st_dev,info.st_ino),host_media=host_media,
                shared_media=self.shared_media,native_media=self.native_media,_live_update=self.LIVE_UPDATE)
        if fresh['tracking_counts']!=self.report['tracking_counts']:
            raise RuntimeError('Tracking changed')
        effective=validate_live_binding(settings=self.env,for_execution=True)
        payload,xml=live_metadata(current=normalized,image=self.image,template=self.data['current-template.xml'],
            environment=self.env,reference=self.report['reference'],host_logs=self.host_logs,
            host_control=self.host_control,host_media=host_media,attempt=self.payload['Labels'][LABEL],
            effective_settings=effective,_live_update=self.LIVE_UPDATE)
        if payload!=self.payload or xml!=self.xml:
            raise RuntimeError('Proposal reconstruction changed')
        if _capture(self.review, REVIEW_FILES)!=self.files or self.inventory()!=self.original_templates:
            raise RuntimeError('Inputs changed during validation')


class SelectedLiveUpdate(SelectedLive):
    REVIEW_STATUS='live_update_cutover_review_prepared'
    LIVE_UPDATE=True

    @staticmethod
    def load_backup(**selected):
        from scripts.unraid_live_update_backup import load_backup_payloads as load_live
        return load_live(**selected)[0]


def run_selected(update, *, action, parent, reviewed_new_id=None):
    if action=='check':
        update.validate()
        return {'status':'live_handoff_preflight_verified','service_changes_performed':False,
            'media_actions_authorized':False,'permanent_deletion_authorized':False,
            'initial_maximum_actions':1,'reference':update.report['reference']}
    from app.sqlite_lock import _exclusive_lock
    with _exclusive_lock(update.review/'.handoff.lock','Handoff already active'):
        common=dict(engine=update.engine,captured=update.captured,payload=update.payload,
            image_id=update.image['Id'],validator=validate_live_container)
        if action=='deploy':
            result=handoff(**common,journal=Journal(parent),precheck=update.validate,install=update.install,
                live_canary=True,health=lambda identity:verify_http_health(engine=update.engine,
                    identity=identity,env=update.env,live_canary=True))
            result.update(status='live_canary_update_complete',media_actions_authorized=True,
                initial_maximum_actions=1,permanent_deletion_authorized=False)
            return result
        if action!='recover':raise ValueError('Known action required')
        old_env=dict(item.split('=',1) for item in update.captured['Config']['Env'])
        result=recover(**common,journal=Journal(parent,'recovery'),new_id=update.recovery_id(reviewed_new_id),
            precheck=lambda:update.validate(recovery=True),restore_template=lambda:update.install(restore=True),
            health=lambda identity:verify_http_health(engine=update.engine,identity=identity,env=old_env,live_canary=update.LIVE_UPDATE))
        result['status']='unchanged_live_previous_recovered' if update.LIVE_UPDATE else 'unchanged_live_canary_preview_recovered'
        return result


def main():
    import argparse,json,re
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('action',choices=('check','deploy','recover'))
    for key in ('review-identity','review-fingerprint','backup-identity','backup-fingerprint','daemon-id'):
        parser.add_argument('--'+key,required=True)
    parser.add_argument('--reviewed-new-id')
    parser.add_argument('--live-update',action='store_true')
    args=parser.parse_args()
    def identity(raw):
        if not re.fullmatch(r'[0-9]+:[0-9]+',raw):raise ValueError('Directory identity required')
        return tuple(map(int,raw.split(':')))
    try:
        selected_class=SelectedLiveUpdate if args.live_update else SelectedLive
        update=selected_class(engine=Docker(endpoint='/var/run/docker.sock',expected_daemon=args.daemon_id),
            review=Path('/review'),review_identity=identity(args.review_identity),review_fingerprint=args.review_fingerprint,
            backup=Path('/backup'),backup_identity=identity(args.backup_identity),backup_fingerprint=args.backup_fingerprint,
            logs=Path('/app/logs'),control=Path('/sqlite-control'),old_logs=Path('/old-logs'),
            old_control=Path('/old-control'),templates=Path('/templates'))
        fd=_open_directory('/review')
        try:result=run_selected(update,action=args.action,parent=fd,reviewed_new_id=args.reviewed_new_id)
        finally:os.close(fd)
    except Exception as error:
        print(json.dumps({'status':'live_handoff_stopped_for_review','error_type':type(error).__name__,
            'automatic_restoration':False,'media_actions_authorized':False}));return 2
    print(json.dumps(result,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
