"""Plan metadata quarantine only when enabled. Never delete media or retry automatically."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timezone,timedelta
import re

STATE_KEY='json_orphan_cleanup'
CONSENT_KEY='ORPHAN_QUARANTINE_CONSENT'
CONSENT_VERSION='metadata-quarantine-v1'
GRACE=timedelta(hours=24)
LIMIT=10000
WARNING=('Orphan cleanup moves known leftover metadata folders into the hidden .auditor-orphans '
    'directory under the media root. It does not permanently delete anything or send Arr updates. '
    'A complete recursive check must find no video, stream pointer or disc media; unknown files, '
    'links, unreadable folders and Keep folders are preserved. Fresh Arr and Jellyfin checks '
    'must both confirm the title is absent. The same folder must remain unchanged across '
    'observations at least 24 hours apart. Cleanup shares the existing five-action limit per library. '
    'Dry Run only previews. Quarantined files are retained until you explicitly restore or remove them.')


class OrphanRecheckBlocked(RuntimeError):
    pass


def validate_consent(settings):
    from app.json_readonly_scan import _bool
    enabled=_bool(settings,'ORPHAN_CLEANUP_ENABLED','false')
    if enabled and settings.get(CONSENT_KEY)!=CONSENT_VERSION:
        raise ValueError('Acknowledge the orphan metadata quarantine warning before enabling cleanup.')
    return enabled


def control(state):
    value=deepcopy(state.get(STATE_KEY,{'schema_version':1,'observations':{},'quarantined':{}}))
    if (not isinstance(value,dict) or set(value)!= {'schema_version','observations','quarantined'}
            or type(value['schema_version']) is not int or value['schema_version']!=1
            or any(not isinstance(value[key],dict) or len(value[key])>LIMIT for key in ('observations','quarantined'))):
        raise RuntimeError('Orphan quarantine tracking requires review')
    return value


def instant(value):
    value=datetime.fromisoformat(value) if isinstance(value,str) else value
    if not isinstance(value,datetime) or value.tzinfo is None: raise ValueError('Aware observation time required')
    return value.astimezone(timezone.utc)


def candidate_records(plan):
    selected={(row.library,row.media_key) for row in plan.get('orphans',())}
    return [deepcopy(row) for row in plan.get('metadata_observations',())
        if (row['library'],row['media_key']) in selected and row['stage']!='Keep' and row['status']=='metadata_only']


def observation(row):
    from app.title_identity import validate_title_folder
    from app.filesystem_paths import _canonical
    validate_title_folder(row['title'])
    if (row['library'] not in ('Movies','TV') or row['stage'] not in ('Waiting','Holding','Removal')
            or row['title'].startswith('.') or row['media_key']!=('TV/' if row['library']=='TV' else '')+row['title']
            or re.fullmatch('[0-9a-f]{64}',row['fingerprint']) is None
            or _canonical(row['source_root'])=='/'
            or any(not isinstance(row[key],list) or len(row[key])!=2
                or any(type(n) is not int or n<0 for n in row[key]) for key in ('identity','root_identity'))):
        raise ValueError('Exact metadata-only folder required')
    return {key:deepcopy(row[key]) for key in ('library','media_key','title','stage','source_root','identity','root_identity','fingerprint')}


def plan_cleanup(state,plan,settings,now):
    now=instant(now);saved=control(state);enabled=validate_consent(settings)
    ready=[];updates={};reasons={}
    for row in candidate_records(plan):
        item=observation(row);key=item['media_key'];old=saved['observations'].get(key)
        first=now
        if isinstance(old,dict) and old.get('folder')==item:
            first=instant(old['first_observed_at'])
            if first>now or instant(old['last_observed_at'])>now: first=now
        updates[key]={'folder':item,'first_observed_at':first.isoformat(),'last_observed_at':now.isoformat()}
        reason=('orphan_cleanup_disabled' if not enabled else 'orphan_observation_wait'
            if now-first<GRACE else 'orphan_quarantine_ready')
        reasons[row['library'],key]=reason
        if reason=='orphan_quarantine_ready':ready.append(row)
    if len(updates)>LIMIT:raise RuntimeError('Metadata observation bound exceeded')
    saved['observations']=updates
    return {'control':saved,'ready':ready,'reasons':reasons}


def record_observations(session,planned):
    session.verify()
    value=planned['control']
    if (STATE_KEY in session.state or value['observations']) and session.state.get(STATE_KEY)!=value:
        session.state[STATE_KEY]=deepcopy(value);session.checkpoint()


def decisions(plan,planned):
    result=[]
    for row in plan['decisions']:
        data=asdict(row)
        reason=planned['reasons'].get((row.library,row.media_key))
        if reason:data.update(reason=reason,outcome='quarantine_proposed' if reason=='orphan_quarantine_ready' else 'skipped')
        result.append(data)
    return tuple(result)
