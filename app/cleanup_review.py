"""Allowlisted, recorded-only metadata cleanup review. No service or media access."""
import re
from app.orphan_cleanup import control, observation, instant, GRACE
from app.scan_results import recorded_details
from app.filesystem_paths import _canonical

BLOCKERS = {
    'no_video','no_video_unknown_files','orphan_keep_preserved','no_video_arr_managed',
    'orphan_arr_unverified','orphan_jellyfin_unverified','orphan_metadata',
    'orphan_cleanup_disabled','orphan_observation_wait','orphan_quarantine_ready','orphan_recheck_blocked',
}


def review(state, history, *, view='observing', query='', library='all', page=1):
    if (view not in ('observing','blocked','quarantined') or library not in ('all','Movies','TV')
            or not isinstance(query,str) or len(query)>255 or type(page) is not int or not 1<=page<=4000):
        raise ValueError('Invalid review filters')
    saved=control(state)
    observing=[]
    for key,row in saved['observations'].items():
        folder=observation(row['folder'])
        if key!=folder['media_key']:raise ValueError('Invalid recorded observation')
        first,last=instant(row['first_observed_at']),instant(row['last_observed_at'])
        if last<first:raise ValueError('Invalid recorded interval')
        elapsed=(last-first).total_seconds()
        observing.append(dict(title=folder['title'],library=folder['library'],stage=folder['stage'],
            first=first.isoformat(),last=last.isoformat(),hours=round(min(elapsed/3600,24),1),
            reason='Observation period recorded; fresh checks still required.' if last-first>=GRACE
                   else 'Waiting for unchanged live observations at least 24 hours apart.'))
    receipts=[]
    for archive,row in saved['quarantined'].items():
        if not isinstance(archive,str) or re.fullmatch('[0-9a-f]{32}',archive) is None:
            raise ValueError('Invalid recorded receipt')
        folder=observation(row['folder'])
        if row.get('archive',archive)!=archive:raise ValueError('Conflicting recorded receipt')
        path=row.get('quarantine_path')
        if path is not None and (not isinstance(path,str) or _canonical(path)=='/'):
            raise ValueError('Invalid recorded location')
        receipts.append(dict(title=folder['title'],library=folder['library'],stage=folder['stage'],
            archive=archive,observed=instant(row['observed_at']).isoformat(),
            original=folder['source_root']+'/'+folder['title'],
            location=path+'/'+archive if path is not None else None))
    blocked=[];partial=True;latest=None
    record=next((row for row in history if isinstance(row,dict) and row.get('worker_mode')=='json_serialized'),None)
    if record is not None:
        try:
            details,partial=recorded_details(record)
            latest=instant(record['started_at']).isoformat()
            keys={(row['library'],row['title']) for row in observing}
            blocked=[dict(title=row['title'],library=row['library'],stage=row['stage'],reason=row['reason'])
                     for row in details if row['reason_code'] in BLOCKERS and row['outcome']!='quarantined'
                     and (row['library'],row['title']) not in keys]
        except (ValueError,TypeError,KeyError):
            partial=True;latest=None
    groups={'observing':observing,'blocked':blocked,'quarantined':receipts}
    rows=[row for row in groups[view] if (library=='all' or row['library']==library)
          and query.casefold() in row['title'].casefold()]
    rows.sort(key=lambda row:(row['library'],row['title'].casefold()))
    pages=max(1,(len(rows)+24)//25);page=min(page,pages)
    return dict(items=rows[(page-1)*25:page*25],counts={key:len(value) for key,value in groups.items()},
                matched=len(rows),page=page,pages=pages,view=view,query=query,library=library,
                latest=latest,partial=partial)
