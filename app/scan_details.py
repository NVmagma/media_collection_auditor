"""Bounded, redacted title observations. Never grant execution or replay authority."""

if __package__:
    from .title_identity import validate_title_folder
else:
    from title_identity import validate_title_folder

LIMIT = 100

REASONS = {
    'protected': 'Protected by keep-forever; preserve the entire title.',
    'keep_tag': 'Selected with the Jellyfin keep tag.',
    'favorite': 'Selected by Jellyfin favorite protection.',
    'disliked': 'Selected for Holding by the not-at-all tag.',
    'waiting_expired': 'The Waiting period has elapsed.',
    'holding_expired': 'The Holding period has elapsed.',
    'waiting_period': 'Still inside the Waiting period.',
    'holding_period': 'Still inside the Holding period.',
    'no_transition': 'No move is proposed for this stage.',
    'action_cap': 'Excluded by the action limits for this run.',
    'missing_or_conflicting_clock': 'The saved lifecycle date is missing or conflicts with another stage.',
    'future_content_timestamp': 'TV content has a future modification date; this show was skipped and its clock was preserved.',
    'future_observation': 'The saved lifecycle date is in the future.',
    'jellyfin_unavailable': 'Jellyfin protection information is unavailable.',
    'deletion_not_authorized': 'Permanent deletion is disabled.',
    'unresolved_sqlite_operation': 'An unresolved operation requires review.',
    'discovery_checkpoint_required': 'New or changed lifecycle dates need a checkpoint and fresh plan.',
    'policy_review': 'The lifecycle decision requires review.',
}

_EXPLANATIONS = {
    'Protected by keep-forever tag; all TV seasons preserved.': 'protected',
    'Tagged keep in Jellyfin.': 'keep_tag',
    'Favorited in Jellyfin (legacy favorite support).': 'favorite',
    'Tagged as disliked in Jellyfin.': 'disliked',
    'Waiting period expired without a favorite.': 'waiting_expired',
    'Holding period expired without a favorite.': 'holding_expired',
    'Still inside the waiting period.': 'waiting_period',
    'Still inside the holding period.': 'holding_period',
    'No lifecycle move proposed for this stage.': 'no_transition',
}

OUTCOMES = {'planned':'Proposed; not completed', 'skipped':'Skipped', 'capped':'Action limit',
    'completed':'Move completed', 'uncertain':'Stopped / uncertain', 'not_attempted':'Not attempted'}

STAGES = ('Waiting','Holding','Keep','Removal')

def reason_code(decision):
    blockers=decision.get('blockers') or ()
    if blockers:return next((key for key in blockers if key in REASONS),'policy_review')
    return _EXPLANATIONS.get(decision.get('explanation'),'policy_review')

def project_details(value, *, titles=True):
    """Drop unrecognized fields, paths, payloads and reason text at every boundary."""
    if (not isinstance(value,dict) or type(value.get('schema_version')) is not int or value['schema_version']!=1
            or type(value.get('total_records')) is not int or not 0<=value['total_records']<=100000
            or not isinstance(value.get('items'),(list,tuple)) or len(value['items'])>LIMIT):return None
    rows=[]
    for item in value['items']:
        if not isinstance(item,dict):return None
        if any(not isinstance(item.get(key),str) for key in ('library','stage','reason_code','outcome')):return None
        if (item.get('library') not in ('Movies','TV') or item.get('stage') not in STAGES
                or item.get('destination') not in (*STAGES,None)
                or item.get('reason_code') not in REASONS or item.get('outcome') not in OUTCOMES):return None
        title=item.get('title')
        try:
            if not isinstance(title,str) or len(title)>255: return None
            validate_title_folder(title)
            if any(ord(char)<32 or ord(char)==127 for char in title):return None
        except ValueError:return None
        row={key:item[key] for key in ('library','stage','destination','reason_code','outcome')}
        row.update(reason=REASONS[row['reason_code']],outcome_label=OUTCOMES[row['outcome']])
        if titles:row['title']=title
        rows.append(row)
    if value['total_records']<len(rows):return None
    return {'schema_version':1,'total_records':value['total_records'],'items':rows,
        'truncated':value['total_records']>len(rows),'scope':'current_process','replay_authorized':False}
