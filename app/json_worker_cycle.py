"""One serialized JSON lifecycle cycle; activation belongs to the service layer.

Settings are detached per attempt. Preview never saves state. Live work records
admission before collection and keeps partial outcomes distinct from proposals.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import PurePosixPath
from time import monotonic
from zoneinfo import ZoneInfo

from app.json_move_execution import MoveRequest, execute_move
from app.json_readonly_scan import collect_worker_scan, rehearse_scan, _bool, _days
from app.json_scan_control import KEY, scan_attempt, ScanAdmissionBlocked
from app.arr_catalog import ArrCatalogGET, canonical_arr_record_path, catalog_paths_by_folder
from app.arr_title_transport import ArrTitleUpdate
from app.jellyfin_collection import collect_title_observation, validated_tag_names
from app.lifecycle_stages import CLOCKS
from app.filesystem_paths import _canonical
from app.jellyfin_transport import ScheduledJellyfinGET


def validate_policy(settings):
    values=deepcopy(settings)
    if not isinstance(values,dict): raise ValueError('Explicit settings required')
    from app.deletion_policy import validate_consent
    validate_consent(values)
    from app.orphan_cleanup import validate_consent as validate_orphan_consent
    validate_orphan_consent(values)
    for flag in ('ALLOW_FILESYSTEM_DELETE',
                 'ALLOW_CROSS_FILESYSTEM_MOVES','ENABLE_SEASON_PRUNING'):
        if _bool(values,flag,'false'): raise ValueError('Unsupported destructive policy')
    limit=_days(values,'MAX_ACTIONS_PER_RUN','10')
    if not 1 <= limit <= 10: raise ValueError('One through ten total actions required')
    values['JSON_PER_LIBRARY_ACTION_LIMIT']='5'
    return values,limit


def stage_paths(values,library):
    prefix='SONARR' if library == 'TV' else 'RADARR'
    base=_canonical(values.get('MEDIA_PATH','/media').strip())
    local,remote={},{}
    for stage,field,suffix in (('Waiting','TRANSIENT',''),('Holding','HOLDING','_hold'),
                              ('Keep','KEEP','_keep'),('Removal','REMOVAL','_removal')):
        local[stage]=_canonical(values.get(prefix+'_'+field+'_PATH','').strip() or base+'/'+library+suffix)
        alias=values.get(prefix+'_APP_'+stage.upper()+'_PATH','') if stage != 'Waiting' else ''
        remote[stage]=_canonical(alias or local[stage])
    return local,remote


class JSONMoveServices:
    """Fresh per-candidate reads; never reuse scan-time protection as move proof."""
    def __init__(self,values): self.values,_=validate_policy(values)

    def prepare(self,decision,session):
        values=self.values; library=decision.library
        title=decision.media_key[3:] if library == 'TV' else decision.media_key
        prefix,service=('SONARR','sonarr') if library == 'TV' else ('RADARR','radarr')
        local,remote=stage_paths(values,library)
        rows=ArrCatalogGET(service=service,base_url=values.get(prefix+'_URL',''),
            token=values.get(prefix+'_API_KEY',''))()
        catalog_paths_by_folder(lambda: rows)  # Reject malformed/duplicate identities before selection.
        matches=[row for row in rows if PurePosixPath(canonical_arr_record_path(row['path'])).name == title]
        if len(matches) != 1 or canonical_arr_record_path(matches[0]['path']) != remote[decision.stage]+'/'+title:
            raise RuntimeError('Selected Arr source changed')
        row=matches[0]
        monitored=((row['monitored'] if decision.stage == 'Waiting' else True)
                   if decision.destination == 'Keep' else False)
        days=_days(values,('TV_WAIT_DAYS' if library == 'TV' else 'MOVIE_WAIT_DAYS')
            if decision.stage == 'Waiting' else 'HOLDING_DAYS',
            ('60' if library == 'TV' else '30') if decision.stage == 'Waiting' else '7')
        request=MoveRequest(library,title,decision.stage,decision.destination,
            session.state[CLOCKS[decision.stage]][decision.media_key],days,
            local[decision.stage],local[decision.destination],service,row['id'],
            remote[decision.stage]+'/'+title,remote[decision.destination],monitored)
        client=ArrTitleUpdate(service=service,base_url=values.get(prefix+'_URL',''),
            token=values.get(prefix+'_API_KEY',''),source_path=request.arr_source_path,
            title_folder=title,verify_binding=session.verify)
        def preflight(req):
            return client._request('GET',client._url+'/'+str(req.title_id),monotonic()+30)
        def complete(req):
            return client(dict(service=req.service,title_id=req.title_id,
                root=req.arr_destination_root,monitored=req.monitored))
        return request,preflight,complete

    def prepare_delete(self,decision,session):
        from app.json_delete_execution import DeleteRequest
        from app.arr_delete_transport import ArrTitleDelete
        library=decision.library; title=decision.media_key[3:] if library=='TV' else decision.media_key
        prefix,service=('SONARR','sonarr') if library=='TV' else ('RADARR','radarr')
        local,remote=stage_paths(self.values,library)
        rows=ArrCatalogGET(service=service,base_url=self.values.get(prefix+'_URL',''),
            token=self.values.get(prefix+'_API_KEY',''))()
        catalog_paths_by_folder(lambda: rows)
        matches=[row for row in rows if PurePosixPath(canonical_arr_record_path(row['path'])).name==title]
        if len(matches)!=1 or canonical_arr_record_path(matches[0]['path'])!=remote['Removal']+'/'+title: raise RuntimeError('Exact Removal Arr record required')
        req=DeleteRequest(library,title,session.state['in_removal'][decision.media_key],
            _days(self.values,'REMOVAL_DAYS','7'),local,service,matches[0]['id'],remote['Removal']+'/'+title,self.values.get(prefix+'_URL',''))
        client=ArrTitleDelete(service=service,base_url=self.values.get(prefix+'_URL',''),
            token=self.values.get(prefix+'_API_KEY',''),source_path=req.arr_source_path,
            title_folder=title,verify_binding=session.verify)
        return req,lambda req:client.read(req.title_id),lambda req:client.delete(req.title_id),lambda req:client.read_absence(req.title_id)

    def authorize_delete(self):
        from app.json_worker_service import settings_snapshot
        # No stale queued settings may retain destructive authority after a change.
        current,_=validate_policy(settings_snapshot())
        if _bool(current,'DRY_RUN','true') or not _bool(current,'ALLOW_PERMANENT_DELETE','false'):
            raise RuntimeError('Live deletion consent was revoked')
        if current != self.values: raise RuntimeError('Settings changed; request a fresh scan')

    def authorize_orphan(self):
        from app.json_worker_service import settings_snapshot
        from app.orphan_cleanup import validate_consent
        current,_=validate_policy(settings_snapshot())
        if current!=self.values or _bool(current,'DRY_RUN','true') or not validate_consent(current):
            raise RuntimeError('Orphan cleanup settings changed or consent was revoked')

    def orphan_absence(self,folder):
        import unicodedata
        values=self.values;library=folder['library'];title=folder['title']
        prefix,service=('SONARR','sonarr') if library=='TV' else ('RADARR','radarr')
        local,remote=stage_paths(values,library)
        expected={local[folder['stage']]+'/'+title,remote[folder['stage']]+'/'+title}
        fold=lambda text:unicodedata.normalize('NFC',text).casefold()
        try:
            def absent():
                rows=ArrCatalogGET(service=service,base_url=values.get(prefix+'_URL',''),token=values.get(prefix+'_API_KEY',''))()
                catalog_paths_by_folder(lambda: rows)
                for row in rows:
                    path=canonical_arr_record_path(row['path'])
                    if fold(PurePosixPath(path).name)==fold(title) or any(path==p or path.startswith(p+'/') or p.startswith(path+'/') for p in expected):return False
                return True
            if not absent():return False
            tags=validated_tag_names({name:values.get(key,default) for name,key,default in (
                ('keep','KEEP_TAG','keep'),('disliked','DISLIKE_TAG','not-at-all'),
                ('keep_all','KEEP_ALL_SEASONS_TAG','keep-all-seasons'),('protected','PROTECT_TAG','keep-forever'))})
            result=collect_title_observation(fetch=ScheduledJellyfinGET(base_url=values.get('JELLYFIN_HOST_URL',''),
                token=values.get('JELLYFIN_API_TOKEN','')),jellyfin_type='Series' if library=='TV' else 'Movie',
                folder=title,media_key=folder['media_key'],now=datetime.now(),tag_names=tags)
            return result.get('absence_verified') is True and absent()
        except Exception:return False

    def protection(self,request,now):
        values=self.values
        tags=validated_tag_names({name:values.get(key,default) for name,key,default in (
            ('keep','KEEP_TAG','keep'),('disliked','DISLIKE_TAG','not-at-all'),
            ('keep_all','KEEP_ALL_SEASONS_TAG','keep-all-seasons'),('protected','PROTECT_TAG','keep-forever'))})
        # A new transport and uncached complete observation for every move.
        fetch=ScheduledJellyfinGET(base_url=values.get('JELLYFIN_HOST_URL',''),
            token=values.get('JELLYFIN_API_TOKEN',''))
        result=collect_title_observation(fetch=fetch,jellyfin_type='Series' if request.library == 'TV' else 'Movie',
            folder=request.title,media_key=('TV/' if request.library == 'TV' else '')+request.title,
            now=now,tag_names=tags)
        return result['signals'] if result['status'] == 'shape_valid_untrusted' and not result['blockers'] else None


def run_cycle(store, *, settings, trigger, now=None, services=None, collect=collect_worker_scan,
              preview=rehearse_scan):
    evidence={}
    try:
        return _run_cycle(store,settings=settings,trigger=trigger,now=now,services=services,
            collect=collect,preview=preview,evidence=evidence)
    except ScanAdmissionBlocked:
        raise
    except Exception as error:
        if not evidence: raise
        # A failed final state verification must not erase independently verified
        # earlier completions, or turn an unreadable journal into "no pending work".
        return {**deepcopy(evidence),'result':'failed','failure_stage':'storage_revalidation',
            'error_type':type(error).__name__,'pending_operation_present':None,
            'completed_moves':tuple(evidence['completed_moves']),
            'completed_deletions':tuple(evidence.get('completed_deletions',())),
            'completed_quarantines':tuple(evidence.get('completed_quarantines',())),
            'permanent_deletion_authorized':False}


def _run_cycle(store, *, settings, trigger, now, services, collect, preview, evidence):
    from app.scan_progress import emit
    values,limit=validate_policy(settings)
    now=datetime.now(timezone.utc) if now is None else now
    if not isinstance(now,datetime) or now.tzinfo is None: raise ValueError('Aware cycle time required')
    zone=ZoneInfo(values.get('DAILY_RUN_TIMEZONE') or values.get('TZ') or 'UTC')
    local_now=now.astimezone(zone).replace(tzinfo=None)
    if _bool(values,'DRY_RUN','true'):
        result=preview(state_file=store.path,settings=values,now=local_now)
        return {**result,'execution_mode':'preview','completed_moves':(), 'result':'completed'}
    adapter=JSONMoveServices(values) if services is None else services
    with scan_attempt(store,now=now,trigger=trigger) as attempt:
        report=evidence
        report.update(execution_mode='live',scanned_titles=None,decisions=(),
                completed_moves=[],completed_deletions=[],completed_quarantines=[],discovery_changes=None,failure_stage=None)
        phase='collection'
        try:
            plan=collect(attempt.session,settings=values,now=local_now)
            from app.orphan_cleanup import plan_cleanup,record_observations,decisions as orphan_decisions
            cleanup=plan_cleanup(attempt.session.state,plan,values,now)
            record_observations(attempt.session,cleanup)
            report.update(scanned_titles=plan['scanned_titles'],
                decisions=orphan_decisions(plan,cleanup),
                discovery_changes=plan['clock_changes_applied'])
            emit('execution')
            for decision in plan['moves'][:limit]:
                phase='candidate_preparation'
                request,preflight,complete=adapter.prepare(decision,attempt.session)
                # The adapter cannot substitute a different title or transition.
                key=('TV/' if request.library == 'TV' else '')+request.title
                if (request.library, key, request.source_stage,request.destination_stage) != (
                    decision.library,decision.media_key,decision.stage,decision.destination):
                    raise RuntimeError('Selected request differs from plan')
                phase='move_and_sync'
                execute_move(attempt,request=request,now=local_now,
                    fetch_protection=lambda req:adapter.protection(req,local_now),
                    arr_preflight=preflight,arr_complete=complete,
                    favorites_trigger_keep=_bool(values,'FAVORITES_TRIGGER_KEEP','true'),
                    tv_reset=_bool(values,'TV_NEW_EPISODES_RESET_CLOCK','true'),timezone_info=zone,per_library_limit=5)
                report['completed_moves'].append(asdict(decision))
            for decision in plan.get('deletions',())[:max(0,limit-len(report['completed_moves']))]:
                from app.json_delete_execution import execute_delete,DeletionPreflightBlocked
                phase='deletion_preparation'
                req,read,send,absent=adapter.prepare_delete(decision,attempt.session)
                if (req.library,('TV/' if req.library=='TV' else '')+req.title,decision.stage) != (decision.library,decision.media_key,'Removal'):
                    raise RuntimeError('Deletion request differs from plan')
                phase='arr_deletion'
                try:
                    execute_delete(attempt,request=req,now=local_now,fetch_protection=lambda req:adapter.protection(req,local_now),
                        read_record=read,send_delete=send,read_absence=absent,authorize=adapter.authorize_delete,timezone_info=zone)
                except DeletionPreflightBlocked as error:
                    attempt.session.verify()
                    if attempt.session.state[KEY]['journal'] is not None: raise
                    report['decisions']=tuple({**row,'outcome':'skipped','reason':error.reason} if
                        (row['library'],row['media_key'])==(decision.library,decision.media_key) else row
                        for row in report['decisions'])
                    continue
                report['completed_deletions'].append(asdict(decision))
            for folder in cleanup['ready']:
                from app.json_orphan_quarantine import execute_quarantine
                from app.orphan_cleanup import OrphanRecheckBlocked
                selected=(folder['library'],folder['media_key'])
                def update_orphan(reason,outcome):
                    report['decisions']=tuple({**row,'reason':reason,'outcome':outcome} if
                        (row['library'],row['media_key'])==selected else row for row in report['decisions'])
                used=len(report['completed_moves'])+len(report['completed_deletions'])+len(report['completed_quarantines'])
                if used>=limit or attempt._move_counts.get(folder['library'],0)>=5:
                    update_orphan('action_cap','capped');continue
                phase='metadata_quarantine'
                try:
                    outcome=execute_quarantine(attempt,row=folder,settings=values,now=now,
                        fresh_absence=adapter.orphan_absence,authorize=adapter.authorize_orphan)
                except OrphanRecheckBlocked:
                    attempt.session.verify()
                    if attempt.session.state[KEY]['journal'] is not None:raise
                    update_orphan('orphan_recheck_blocked','skipped');continue
                report['completed_quarantines'].append({**{key:folder[key] for key in ('library','media_key','stage')},
                    'quarantine_id':outcome['quarantine_id']})
            attempt.finish(result='completed')
            report['result']='completed'
        except Exception as error:
            # Never invent missing counts or discard a move that already completed.
            report.update(result='failed',failure_stage=phase,error_type=type(error).__name__)
            journal=attempt.session.state[KEY]['journal']
            if journal:
                report['uncertain_media_key']=('TV/' if journal['library']=='TV' else '')+journal['title']
            if attempt.session.state[KEY]['journal'] is None:
                attempt.finish(result='failed')
        report['pending_operation_present']=attempt.session.state[KEY]['journal'] is not None
        report['completed_moves']=tuple(report['completed_moves'])
        report['completed_deletions']=tuple(report['completed_deletions'])
        report['completed_quarantines']=tuple(report['completed_quarantines'])
        report['permanent_deletion_authorized']=_bool(values,'ALLOW_PERMANENT_DELETE','false')
        from app.jellyfin_refresh import refresh_after_moves
        report['jellyfin_refresh']=refresh_after_moves(settings=values,
            completed=report['result']=='completed' and bool(report['completed_moves'] or report['completed_deletions']))
        return report
