"""Prepare limited title details without private payloads or permission to run actions."""

if __package__:
    from .title_identity import validate_title_folder
else:
    from title_identity import validate_title_folder

LIMIT = 100

REASONS = {
    'no_video': 'No video file was found in this folder.',
    'no_video_unknown_files': 'No recognized video found; unknown files prevent automatic metadata cleanup.',
    'orphan_keep_preserved': 'No video found; Keep folders are preserved.',
    'no_video_arr_managed': 'No video found, but Arr still manages or references this title; folder preserved.',
    'orphan_arr_unverified': 'No video found; Arr absence could not be verified, so the folder is preserved.',
    'orphan_jellyfin_unverified': 'No video found; Jellyfin absence could not be verified, so the folder is preserved.',
    'orphan_metadata': 'Metadata only; complete Arr and Jellyfin checks found no matching title.',
    'orphan_cleanup_disabled': 'Metadata-only orphan detected; recoverable quarantine is disabled.',
    'orphan_observation_wait': 'Metadata-only orphan detected; waiting for 24 hours of unchanged observations.',
    'orphan_quarantine_ready': 'Stable metadata-only orphan; eligible for recoverable quarantine after fresh checks.',
    'orphan_recheck_blocked': 'Fresh Arr/Jellyfin absence was not verified; no quarantine was performed.',
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
    'tv_season_policy': 'This TV show is managed by the season retention policy.',
    'staged_tv_seasons': 'Whole-show actions wait while this show has seasons in Leaving Soon.',
    'missing_or_conflicting_clock': 'The saved lifecycle date is missing or conflicts with another stage.',
    'future_content_timestamp': 'TV content has a future modification date; this show was skipped and its clock was preserved.',
    'future_observation': 'The saved lifecycle date is in the future.',
    'jellyfin_unavailable': 'Jellyfin protection information is unavailable.',
    'removal_content_changed': 'Removal contents are newer than the saved date; deletion was skipped.',
    'deletion_protection_unavailable': 'Fresh Jellyfin protection is unavailable; deletion was skipped.',
    'deletion_arr_changed': 'The exact unmonitored Arr record changed; deletion was skipped.',
    'deletion_protected': 'Jellyfin retention or favorite protection blocks deletion.',
    'removal_period': 'Still inside the Removal waiting period.',
    'removal_expired': 'Removal waiting period elapsed; fresh deletion safeguards are required.',
    'deletion_not_authorized': 'Permanent deletion is disabled.',
    'unresolved_operation': 'An unresolved operation requires review.',
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

OUTCOMES = {'quarantined':'Metadata quarantined (recoverable)', 'planned':'Proposed; not completed', 'skipped':'Skipped', 'capped':'Action limit',
    'deleted':'Arr deletion verified', 'completed':'Move completed', 'uncertain':'Stopped / uncertain', 'not_attempted':'Not attempted'}

STAGES = ('Waiting','Holding','Keep','Removal')

def reason_code(decision):
    blockers=decision.get('blockers') or ()
    if blockers:return next((key for key in blockers if key in REASONS),'policy_review')
    return _EXPLANATIONS.get(decision.get('explanation'),'policy_review')

def project_details(value, *, titles=True):
    """Keep only known fields. Leave out paths, raw payloads, and free-text reasons."""
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
