from app.tracking_schema import has_pending_extension
"""Plan JSON worker actions without collecting data or changing files.

Use complete, verified input. A plan alone does not approve an action; the
executor must recheck protection and paths and save its intent first. Keep every
title result up to the configured collection limit.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from app.lifecycle_decisions import decide
from app.lifecycle_stages import CLOCKS
from app.scan_details import reason_code
from app.tracking_schema import validate_snapshot
from app.title_identity import validate_title_folder
from app.json_scan_control import KEY, _control
from app.tv_season_policy import ARCHIVE

SIGNALS = {'played', 'favorite', 'disliked', 'keep', 'keep_all', 'protected'}
BLOCKERS = {'future_content_timestamp', 'content_unavailable', 'content_reset_required', 'discovery_required','no_video','no_video_unknown_files','tv_season_policy'}
ARR = {'exact_source_match', 'missing_record', 'path_conflict', 'ambiguous_record', 'unavailable'}
DESTINATIONS = {('Waiting','hold'):'Holding', ('Waiting','keep'):'Keep',
    ('Holding','rescue'):'Keep', ('Holding','to_removal'):'Removal'}


@dataclass(frozen=True)
class TitleObservation:
    media_key: str
    stage: str
    threshold_days: int
    signals: dict | None
    arr_status: str
    blocker: str | None = None
    jellyfin_absent: bool = False


@dataclass(frozen=True)
class LibraryObservation:
    library: str
    jellyfin_complete: bool
    arr_complete: bool
    titles: tuple


@dataclass(frozen=True)
class TitleDecision:
    library: str
    media_key: str
    stage: str
    destination: str | None
    reason: str
    outcome: str


def plan_scan(*, snapshot, libraries, now, favorites_trigger_keep=True, maximum_titles=100000, per_library_action_limit=1, deletion_enabled=False):
    if (not isinstance(now, datetime) or now.tzinfo is not None
            or type(favorites_trigger_keep) is not bool or type(maximum_titles) is not int
            or not 1 <= maximum_titles <= 100000 or type(per_library_action_limit) is not int
            or type(deletion_enabled) is not bool or not 1 <= per_library_action_limit <= 5 or not isinstance(libraries, (tuple,list))
            or not 1 <= len(libraries) <= 2):
        raise ValueError('Explicit bounded scan policy required')
    state = deepcopy(snapshot)
    validate_snapshot(state)
    if KEY in state:
        _control(state)  # Invalid worker metadata does not mean there is no pending operation.
    if (has_pending_extension(state) or state.get('arr_sync_pending')
            or isinstance(state.get(KEY), dict) and state[KEY].get('journal') is not None):
        raise RuntimeError('Pending operation requires review')
    captured = deepcopy(libraries)
    names, seen, total = set(), set(), 0
    for library in captured:
        if (not isinstance(library, LibraryObservation) or library.library not in ('Movies','TV')
                or library.library in names or type(library.jellyfin_complete) is not bool
                or type(library.arr_complete) is not bool or not isinstance(library.titles, tuple)):
            raise ValueError('Unique known libraries and complete observations required')
        names.add(library.library)
        for title in library.titles:
            total += 1
            if total > maximum_titles: raise RuntimeError('Collection limit exceeded; no partial plan')
            if (not isinstance(title, TitleObservation) or title.stage not in CLOCKS
                    or type(title.threshold_days) is not int or title.threshold_days < 0
                    or not isinstance(title.arr_status, str) or title.arr_status not in ARR
                    or not isinstance(title.media_key, str)
                    or type(title.jellyfin_absent) is not bool
                    or title.blocker is not None and title.blocker not in BLOCKERS):
                raise ValueError('Invalid title observation')
            key = title.media_key
            prefix = 'TV/' if library.library == 'TV' else ''
            folder = key[3:] if prefix and key.startswith(prefix) else key
            validate_title_folder(folder)
            if key != prefix + folder or folder.startswith('.') or len(folder) > 255 or key in seen:
                raise ValueError('Ambiguous or invalid title identity')
            seen.add(key)
            if title.signals is not None and (not isinstance(title.signals, dict)
                    or not SIGNALS <= title.signals.keys()
                    or any(type(value) is not bool for value in title.signals.values())):
                raise ValueError('Incomplete protection signals')
    season_archive = state.get(ARCHIVE, {})
    if not isinstance(season_archive, dict):
        raise RuntimeError('TV season archive requires review')
    staged_shows = {key.rsplit('/', 1)[0] for key in season_archive}
    decisions, moves, deletions, orphans = [], [], [], []
    deletion_used = {name:0 for name in names}
    used = {name:0 for name in names}
    for library in captured:
        for title in library.titles:
            destination = None
            retain_despite_future_date = (
                library.library == 'TV' and title.stage == 'Waiting'
                and title.blocker == 'future_content_timestamp'
                and library.jellyfin_complete and library.arr_complete
                and title.signals is not None
                and decide(title.stage, None, title.threshold_days,
                           title.signals, favorites_trigger_keep)[0] == 'keep')
            if library.library == 'TV' and title.media_key in staged_shows:
                reason = 'staged_tv_seasons'
            elif title.blocker == 'no_video':
                if title.stage=='Keep': reason='orphan_keep_preserved'
                elif not library.arr_complete: reason='orphan_arr_unverified'
                elif title.arr_status!='missing_record': reason='no_video_arr_managed'
                elif not library.jellyfin_complete or not title.jellyfin_absent: reason='orphan_jellyfin_unverified'
                else: reason='orphan_metadata'
            elif title.blocker is not None and not retain_despite_future_date: reason = title.blocker
            elif not library.jellyfin_complete: reason = 'jellyfin_collection_incomplete'
            elif not library.arr_complete: reason = 'arr_catalog_unavailable'
            elif title.signals is None: reason = 'jellyfin_unavailable'
            elif title.stage == 'Removal':
                from app.deletion_policy import protected
                stamp = state['in_removal'].get(title.media_key)
                if not deletion_enabled: reason = 'deletion_not_authorized'
                elif protected(title.signals): reason = 'deletion_protected'
                elif [section for section in CLOCKS.values() if title.media_key in state[section]] != ['in_removal']:
                    reason = 'missing_or_conflicting_clock'
                elif datetime.fromisoformat(stamp) > now: reason = 'future_observation'
                elif title.threshold_days < 1 or (now-datetime.fromisoformat(stamp)).days < title.threshold_days:
                    reason = 'removal_period'
                else: reason = 'removal_expired'
            else:
                clock = CLOCKS[title.stage]
                matches = [section for section in CLOCKS.values() if title.media_key in state[section]]
                stamp = state[clock].get(title.media_key)
                if matches != [clock]: reason = 'missing_or_conflicting_clock'
                elif datetime.fromisoformat(stamp) > now: reason = 'future_observation'
                else:
                    age = (now-datetime.fromisoformat(stamp)).days
                    action, explanation = decide(title.stage, age, title.threshold_days,
                        title.signals, favorites_trigger_keep)
                    reason = reason_code({'explanation':explanation})
                    destination = DESTINATIONS.get((title.stage, action))
            outcome = 'skipped'
            deleting = title.stage == 'Removal' and reason == 'removal_expired'
            if destination is not None or deleting:
                if title.arr_status != 'exact_source_match':
                    reason = {'missing_record':'arr_record_missing', 'path_conflict':'arr_path_conflict',
                        'ambiguous_record':'arr_record_ambiguous', 'unavailable':'arr_catalog_unavailable'}[title.arr_status]
                    destination = None
                elif used[library.library] >= per_library_action_limit or deleting and deletion_used[library.library] >= 1:
                    reason, outcome = 'action_cap', 'capped'
                else:
                    used[library.library] += 1
                    if deleting: deletion_used[library.library] += 1
                    outcome = 'delete_proposed' if deleting else 'proposed'
            row = TitleDecision(library.library, title.media_key, title.stage, destination, reason, outcome)
            decisions.append(row)
            if outcome == 'proposed': moves.append(row)
            if outcome == 'delete_proposed': deletions.append(row)
            if reason == 'orphan_metadata': orphans.append(row)
    return {'status':'advisory_only', 'read_only':True, 'media_actions_authorized':False,
        'scanned_titles':total, 'decisions':tuple(decisions), 'moves':tuple(moves),
        'maximum_actions':2*per_library_action_limit, 'per_library_action_limit':per_library_action_limit,
        'permanent_deletion_authorized':False,'deletions':tuple(deletions),'orphans':tuple(orphans)}
