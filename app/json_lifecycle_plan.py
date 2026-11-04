"""Pure JSON-worker advisory planning; no collectors, writes, HTTP or moves.

Inputs must come from complete verified adapters. A plan never authorizes an
operation: a future executor must recheck protections/paths and journal intent.
All title observations are retained up to the explicit total collection bound.
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

SIGNALS = {'played', 'favorite', 'disliked', 'keep', 'keep_all', 'protected'}
BLOCKERS = {'future_content_timestamp', 'content_unavailable', 'content_reset_required', 'discovery_required'}
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


def plan_scan(*, snapshot, libraries, now, favorites_trigger_keep=True, maximum_titles=100000, per_library_action_limit=1):
    if (not isinstance(now, datetime) or now.tzinfo is not None
            or type(favorites_trigger_keep) is not bool or type(maximum_titles) is not int
            or not 1 <= maximum_titles <= 100000 or type(per_library_action_limit) is not int
            or not 1 <= per_library_action_limit <= 5 or not isinstance(libraries, (tuple,list))
            or not 1 <= len(libraries) <= 2):
        raise ValueError('Explicit bounded scan policy required')
    state = deepcopy(snapshot)
    validate_snapshot(state)
    if KEY in state:
        _control(state)  # Malformed worker metadata is not equivalent to no journal.
    if ('sqlite_pending_operations' in state or state.get('arr_sync_pending')
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
    decisions, moves = [], []
    used = {name:0 for name in names}
    for library in captured:
        for title in library.titles:
            destination = None
            if title.blocker is not None: reason = title.blocker
            elif not library.jellyfin_complete: reason = 'jellyfin_collection_incomplete'
            elif not library.arr_complete: reason = 'arr_catalog_unavailable'
            elif title.signals is None: reason = 'jellyfin_unavailable'
            elif title.stage == 'Removal': reason = 'deletion_not_authorized'
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
            if destination is not None:
                if title.arr_status != 'exact_source_match':
                    reason = {'missing_record':'arr_record_missing', 'path_conflict':'arr_path_conflict',
                        'ambiguous_record':'arr_record_ambiguous', 'unavailable':'arr_catalog_unavailable'}[title.arr_status]
                    destination = None
                elif used[library.library] >= per_library_action_limit:
                    reason, outcome = 'action_cap', 'capped'
                else:
                    used[library.library] += 1
                    outcome = 'proposed'
            row = TitleDecision(library.library, title.media_key, title.stage, destination, reason, outcome)
            decisions.append(row)
            if outcome == 'proposed': moves.append(row)
    return {'status':'advisory_only', 'read_only':True, 'media_actions_authorized':False,
        'scanned_titles':total, 'decisions':tuple(decisions), 'moves':tuple(moves),
        'maximum_actions':2*per_library_action_limit, 'per_library_action_limit':per_library_action_limit,
        'permanent_deletion_authorized':False}
