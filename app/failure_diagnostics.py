"""Keep useful failure locations without saving exception messages or private paths."""
from pathlib import Path
import re
import traceback

STAGES = frozenset(('worker','collection','candidate_preparation','move_and_sync',
    'deletion_preparation','arr_deletion','metadata_quarantine','tv_season_retention',
    'storage_revalidation'))
_SOURCE = Path(__file__).resolve().parent


def failure_details(error, stage):
    sites = []
    for frame in traceback.extract_tb(error.__traceback__):
        path = Path(frame.filename)
        if path.parent.resolve() == _SOURCE:
            sites.append({'file': path.name, 'line': frame.lineno})
    return clean_failure_details({'failure_stage':stage,'error_type':type(error).__name__,
                                  'failure_sites':sites[-5:]})


def clean_failure_details(result):
    stage = result.get('failure_stage')
    error_type = result.get('error_type')
    details = {'failure_stage':stage if isinstance(stage,str) and stage in STAGES else None,
               'error_type':error_type if isinstance(error_type,str) and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,79}',error_type) else None}
    sites = result.get('failure_sites')
    details['failure_sites'] = [dict(file=row['file'],line=row['line']) for row in sites[:5]
        if isinstance(row,dict) and isinstance(row.get('file'),str)
        and re.fullmatch(r'[a-zA-Z_][a-zA-Z_0-9]*[.]py',row['file'])
        and (_SOURCE/row['file']).is_file() and type(row.get('line')) is int
        and 1 <= row['line'] <= 1000000] if isinstance(sites,list) else []
    return details
