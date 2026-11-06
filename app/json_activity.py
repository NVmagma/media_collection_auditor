"""Allowlisted activity projection from recorded JSON scan history.

No collection, execution, raw request payloads or exception text. Proposals stay
proposals; only the worker's verified completion observations say completed.
"""
from datetime import datetime
import json
from app.scan_details import project_details


def _time(value):
    if not isinstance(value,str) or len(value)>64: return None
    try:
        parsed=datetime.fromisoformat(value)
        return parsed.isoformat() if parsed.tzinfo is not None else None
    except ValueError: return None


def _count(value):
    return str(value) if type(value) is int and 0<=value<=100000 else 'unknown'


def project_activity(records,limit=1000):
    if type(limit) is not int or not 0<=limit<=1000: raise ValueError('Bounded activity limit required')
    events=[]
    for record in records[:100]:
        if not isinstance(record,dict) or record.get('worker_mode')!='json_serialized': continue
        when=_time(record.get('finished_at')) or _time(record.get('started_at'))
        if when is None: continue
        result=record.get('result')
        completed=(result=='completed' and record.get('result_basis')=='worker_return' and _time(record.get('finished_at')) is not None)
        status='completed' if completed else 'failed' if result=='failed' else 'unknown'
        detail=('Recorded scan result. ' if completed else 'Blocked, uncertain or incomplete scan result. ')
        detail+='Verified moves: '+_count(record.get('moves_completed'))+'. Verified deletions: '+_count(record.get('deletions_completed'))+'. Metadata quarantines: '+_count(record.get('metadata_quarantines_completed'))+'. Tracking date changes: '+_count(record.get('discovery_changes'))+'.'
        if record.get('season_moves_completed'):
            detail += ' Verified season moves: ' + _count(record['season_moves_completed']) + '.'
        events.append(dict(time=when,library='All',action='scan',status=status,folder='-',detail=detail))
        details=project_details(record.get('title_details'))
        if details:
            for item in details['items']:
                transition=item['stage']+(' to '+item['destination'] if item['destination'] else '')
                recovery=''
                if item['outcome']=='quarantined':
                    import re
                    receipts=record.get('quarantine_receipts',())
                    if not isinstance(receipts,(list,tuple)):receipts=()
                    for receipt in receipts[:10]:
                        if (isinstance(receipt,dict) and receipt.get('library')==item['library']
                                and receipt.get('media_key')==('TV/' if item['library']=='TV' else '')+item['title']
                                and isinstance(receipt.get('quarantine_id'),str)
                                and re.fullmatch('[0-9a-f]{32}',receipt['quarantine_id'])):
                            recovery=' Recovery ID: '+receipt['quarantine_id']+'.'
                events.append(dict(time=when,library=item['library'],action=transition,
                    status=item['outcome'],folder=item['title'],detail=item['outcome_label']+'. '+item['reason']+recovery))
        if len(events)>=limit: break
    return events[:limit]


def export_activity(records):
    """Keep whole recent records within the diagnostic's existing two-MiB limit."""
    rows=[];total=0
    for event in project_activity(records):
        raw=(json.dumps(event,ensure_ascii=False)+'\n').encode()
        if total+len(raw)>2*1024*1024: break
        rows.append(raw);total+=len(raw)
    return b''.join(rows)
