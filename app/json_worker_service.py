"""Explicit JSON service selection, one active scan, daily schedule and history."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import os
import re
from threading import Event,Lock
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.json_readonly_scan import _bool
from app.json_scan_control import admission_status
from app.json_tracking_store import JsonTrackingStore
from app.json_worker_cycle import run_cycle,validate_policy


def enabled():
    return os.environ.get('AUDITOR_WORKER_MODE') == 'json_serialized'


def read_saved_settings():
    """A missing/corrupt file pauses this worker; never reactivate live defaults."""
    from config_store import CONFIG_FILE
    from app.filesystem_paths import _open_directory
    from app.private_files import _local
    from app.json_validation import parse_unique_json
    try:
        parent=_open_directory(str(CONFIG_FILE.parent))
        try: raw=_local(parent,CONFIG_FILE.name)[0]
        finally: os.close(parent)
        if len(raw)>2*1024*1024: raise ValueError('Settings too large')
        saved=parse_unique_json(raw)
        if not isinstance(saved,dict): raise ValueError('Settings object required')
        return saved
    except Exception:
        raise ValueError('Stored settings could not be read; scans remain paused.') from None


def settings_snapshot():
    from config_store import DEFAULTS,KEYS,initial_environment,validate
    from app.legacy_settings import normalize_schedule
    saved=normalize_schedule(read_saved_settings())
    try: selected={key:validate(key,str(value)) for key,value in saved.items() if key in KEYS}
    except Exception:
        raise ValueError('Stored settings are invalid; scans remain paused.') from None
    from app.deletion_policy import CONSENT_KEY
    from app.orphan_cleanup import CONSENT_KEY as ORPHAN_CONSENT
    return {**DEFAULTS,**initial_environment(),**selected,CONSENT_KEY:saved.get(CONSENT_KEY),ORPHAN_CONSENT:saved.get(ORPHAN_CONSENT)}


def next_daily(settings,now):
    if now.tzinfo is None: raise ValueError('Aware schedule clock required')
    raw=settings.get('DAILY_RUN_TIME') or '02:00'
    if not isinstance(raw,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',raw):
        raise ValueError('Daily time must be HH:MM')
    zone=ZoneInfo(settings.get('DAILY_RUN_TIMEZONE') or settings.get('TZ') or 'UTC')
    hour,minute=map(int,raw.split(':')); day=now.astimezone(zone).date()
    for offset in range(370):
        candidate=datetime.combine(day+timedelta(days=offset),datetime.min.time()).replace(
            hour=hour,minute=minute,tzinfo=zone,fold=0)
        utc=candidate.astimezone(timezone.utc)
        # Skip nonexistent spring-forward local times; use only the first fall fold.
        if utc.astimezone(zone).replace(tzinfo=None) != candidate.replace(tzinfo=None): continue
        if utc > now.astimezone(timezone.utc): return utc
    raise ValueError('Future daily slot unavailable')


class JSONWorkerService:
    def __init__(self,*,clock=lambda:datetime.now(timezone.utc),execute=run_cycle,
                 load_settings=settings_snapshot,record=None,read_records=None):
        self.clock,self.execute,self.load_settings=clock,execute,load_settings
        self.record,self.read_records=record,read_records
        self.lock=Lock(); self.wake=Event(); self.running=False; self.queued=False; self.queued_settings=None
        self.latest=None; self.records=[]; self.next_run=None; self.execution_blocked=False

    def gate(self,values):
        validate_policy(values)
        if _bool(values,'DRY_RUN','true'): return {'status':'ready','retry_after_seconds':0,'next_allowed_at':None}
        with JsonTrackingStore(values.get('STATE_FILE','/app/logs/auditor_state.json')).session() as session:
            return admission_status(session.state,now=self.clock())

    def request(self,*,expected_dry_run=None):
        with self.lock:
            if self.running or self.queued: return {'status':'busy'}
            try:
                values=deepcopy(self.load_settings())
                if expected_dry_run is not None and _bool(values,'DRY_RUN','true') is not expected_dry_run:
                    return {'status':'settings_changed'}
                gate=self.gate(values)
            except Exception: return {'status':'review_required'}
            if gate['status'] != 'ready': return gate
            self.queued_settings=values; self.queued=True; self.wake.set()
            return {'status':'queued'}

    def report(self):
        with self.lock:
            latest=deepcopy(self.latest or {})
            if not latest and self.read_records:
                saved=[row for row in self.read_records(100) if row.get('worker_mode') == 'json_serialized']
                latest=deepcopy(saved[0]) if saved else {}
            try:
                values,limit=validate_policy(self.load_settings())
                dry=_bool(values,'DRY_RUN','true')
                if not self.running and not self.queued:
                    self.execution_blocked=self.gate(values)['status'] == 'review_required'
            except Exception:
                limit,dry=2,True
                values={}
                self.execution_blocked=True
            return dict(status='advisory_only',execution_mode='scheduled_preview' if dry else 'scheduled_live_moves',
                maximum_actions=limit,per_library_action_limit=5,minimum_live_scan_interval_seconds=3600,
                permanent_deletion_authorized=not dry and values.get('ALLOW_PERMANENT_DELETE')=='true',
                per_library_deletion_limit=1, deletions_completed=latest.get('deletions_completed'),running=self.running,queued=self.queued,rescuing=False,
                next_run=self.next_run.isoformat() if self.next_run else None,
                execution_blocked=self.execution_blocked,last_started=latest.get('started_at'),
                last_finished=None if self.running else latest.get('finished_at'),
                last_result=None if self.running else latest.get('result'),last_trigger=latest.get('trigger'),
                metadata_quarantines_completed=latest.get('metadata_quarantines_completed'),
                orphan_cleanup_enabled=values.get('ORPHAN_CLEANUP_ENABLED')=='true',
                moves_completed=latest.get('moves_completed'),moves_proposed=latest.get('moves_proposed'),
                discovery_changes=latest.get('discovery_changes'),dry_run=latest.get('dry_run'),
                result_basis=latest.get('result_basis'),state_revision=None,
                history_scope='persistent' if self.read_records else 'current_process',
                history_persistent=self.read_records is not None,worker_mode='json_serialized',
                storage_authority='json',freshness_verified=False)

    def history(self,limit=100):
        if type(limit) is not int or not 0 <= limit <= 100: raise ValueError('Bounded history required')
        if self.read_records:
            return [row for row in self.read_records(limit) if row.get('worker_mode') == 'json_serialized'][:limit]
        with self.lock: return deepcopy(list(reversed(self.records[-limit:]))) if limit else []

    def run_once(self,*,trigger):
        if trigger not in ('manual','scheduled'): raise ValueError('Known trigger required')
        with self.lock:
            if self.running: raise RuntimeError('A scan is already active')
            if trigger == 'manual' and not self.queued: raise RuntimeError('Manual request required')
            if trigger == 'scheduled' and self.queued: raise RuntimeError('Manual request already queued')
            queued_settings=deepcopy(self.queued_settings)
            self.queued_settings=None
            self.running=True; self.queued=False; self.wake.clear()
            record=dict(id=uuid4().hex,trigger=trigger,started_at=self.clock().isoformat(),finished_at=None,
                result=None,worker_mode='json_serialized',freshness_verified=False,
                result_basis='worker_return',moves_completed=None,arr_completed=None,moves_proposed=None,
                discovery_changes=None,movies_processed=None,tv_processed=None)
            self.latest=deepcopy(record)
        result=None; values=None
        try:
            values=deepcopy(self.load_settings())
            if trigger=='manual' and values!=queued_settings:
                raise ValueError('Queued settings changed; request a fresh scan')
            record['dry_run']=_bool(values,'DRY_RUN','true')
            result=self.execute(JsonTrackingStore(values.get('STATE_FILE','/app/logs/auditor_state.json')),
                settings=values,trigger=trigger,now=self.clock())
            record['result']=result['result']
            record['result_basis']='worker_return' if result['result']=='completed' else 'blocked_or_uncertain'
            decisions=result.get('decisions',())
            decisions=[row if isinstance(row,dict) else asdict(row) for row in decisions]
            completed=result.get('completed_moves',())
            deleted=result.get('completed_deletions',())
            quarantined=result.get('completed_quarantines',())
            record.update(moves_completed=len(completed),deletions_completed=len(deleted),
                metadata_quarantines_completed=len(quarantined),quarantine_receipts=quarantined,
                deletions_proposed=sum(row['outcome']=='delete_proposed' for row in decisions),arr_completed=len(completed)+len(deleted),
                moves_proposed=sum(row['outcome']=='proposed' for row in decisions),
                discovery_changes=result.get('discovery_changes',result.get('clock_changes_applied')),
                scanned_titles=result.get('scanned_titles'),json_decisions=decisions)
            record['title_details']=_title_details(decisions,completed,result.get('result'),result.get('uncertain_media_key'),deleted,quarantined)
            with self.lock: self.execution_blocked=result.get('pending_operation_present') is True
        except Exception as error:
            record.update(result='failed',result_basis='blocked_or_uncertain',error_type=type(error).__name__)
            with self.lock: self.execution_blocked=True
        finally:
            record['finished_at']=self.clock().isoformat()
            try:
                if self.record: self.record(deepcopy(record))
            except Exception:
                record['history_write_failed']=True
                print('[JSON WORKER] History could not be saved; tracking and operation journal were retained.',flush=True)
            with self.lock:
                self.running=False; self.latest=deepcopy(record)
                self.records.append(deepcopy(record)); self.records=self.records[-100:]
        if isinstance(values,dict):
            try:
                from app.operational_notifications import NOTIFICATIONS
                if record['result']=='completed': NOTIFICATIONS.clear('scan_blocked_or_uncertain')
                else: NOTIFICATIONS.emit(values,'scan_blocked_or_uncertain')
            except Exception:
                pass  # Opt-in delivery cannot change tracking or scan results.
        print('[JSON WORKER] Attempt result='+str(record['result'])+
            ' verified_moves='+str(record.get('moves_completed'))+
            ' outcome='+str(record.get('result_basis')),flush=True)
        return record


def _title_details(decisions,completed,result,uncertain=None,deleted=(),quarantined=()):
    from app.scan_details import REASONS,project_details
    finished={(row['library'],row['media_key']) for row in completed}
    quarantine_keys={(row['library'],row['media_key']) for row in quarantined}
    deleted_keys={(row['library'],row['media_key']) for row in deleted}
    # Keep all decisions in private persistent history; existing display shows a bounded page.
    ordered=sorted(decisions,key=lambda row:row['outcome'] not in ('proposed','delete_proposed','quarantine_proposed','capped'))
    items=[]
    for row in ordered[:100]:
        outcome=('quarantined' if (row['library'],row['media_key']) in quarantine_keys else 'deleted' if (row['library'],row['media_key']) in deleted_keys else 'completed' if (row['library'],row['media_key']) in finished else
            'uncertain' if row['media_key']==uncertain else
            'not_attempted' if row['outcome'] in ('proposed','delete_proposed','quarantine_proposed') and result != 'completed' else
            'planned' if row['outcome'] in ('proposed','delete_proposed','quarantine_proposed') else row['outcome'])
        items.append(dict(library=row['library'],title=row['media_key'][3:] if row['library']=='TV' else row['media_key'],
            stage=row['stage'],destination=row['destination'],reason_code=row['reason'] if row['reason'] in REASONS else 'policy_review',outcome=outcome))
    details=project_details(dict(schema_version=1,total_records=len(decisions),items=items))
    if details: details['scope']='persistent'
    return details


SERVICE=JSONWorkerService()


def run_service(*,stop=None):
    from audit_history import append_history,read_history
    SERVICE.record=append_history; SERVICE.read_records=read_history
    stop=Event() if stop is None else stop
    target=None; signature=None; error_reported=False
    while not stop.is_set():
        try:
            values=SERVICE.load_settings(); now=SERVICE.clock()
            current=tuple(values.get(key) for key in ('DAILY_RUN_TIME','DAILY_RUN_TIMEZONE','TZ'))
            if target is None or current != signature: target=next_daily(values,now); signature=current
            with SERVICE.lock: SERVICE.next_run=target; queued=SERVICE.queued
            error_reported=False
            if queued:
                SERVICE.run_once(trigger='manual'); target=next_daily(SERVICE.load_settings(),SERVICE.clock())
            elif now >= target:
                if (now-target).total_seconds() <= 60: SERVICE.run_once(trigger='scheduled')
                target=next_daily(SERVICE.load_settings(),SERVICE.clock())
        except Exception:
            with SERVICE.lock: SERVICE.execution_blocked=True
            if not error_reported:
                print('[JSON WORKER] Configuration or schedule requires review; no fallback worker selected.',flush=True)
                error_reported=True
        SERVICE.wake.wait(1); SERVICE.wake.clear()
