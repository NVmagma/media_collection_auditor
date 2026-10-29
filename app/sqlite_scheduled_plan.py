"""Complete-scan barrier and bounded advisory plan for scheduled SQLite runs.

The injected collector is a read-only dependency, responsible for reporting
complete pagination and authoritative signals. This module cannot sandbox it.
There is deliberately no move, Arr, persistence or deletion callback.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
import math
import os

from app.sqlite_lifecycle_decision_bridge import review_decision
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_state import validate_snapshot


class ScheduledScanBlocked(RuntimeError):
    """No plan may escape a failed, incomplete or expired scan."""


@dataclass(frozen=True)
class ScannedTitle:
    media_key: str
    stage: str
    threshold_days: int
    signals: dict | None


@dataclass(frozen=True)
class LibraryScan:
    complete: bool
    titles: object  # Iterable consumed fully before any lifecycle decision.


@dataclass(frozen=True)
class PlannedMove:
    library: str
    media_key: str
    source_stage: str
    destination_stage: str
    action: str
    source_clock: str
    threshold_days: int


@dataclass(frozen=True)
class ScheduledPlan:
    revision: int
    scanned_at: datetime  # Existing lifecycle clocks use naive local wall time.
    libraries: tuple
    scanned_titles: int
    moves: tuple
    skipped: tuple
    capped_moves: int
    favorites_trigger_keep: bool
    created_tick: float
    deadline_tick: float
    process_id: int
    authorization: str = 'not_authorized'
    title_observations: tuple = ()


_DESTINATIONS = {('Waiting', 'hold'): 'Holding', ('Waiting', 'keep'): 'Keep',
                 ('Holding', 'rescue'): 'Keep', ('Holding', 'to_removal'): 'Removal'}


def collect_scheduled_plan(*, snapshot, revision, libraries, scan_library, now,
                           maximum_actions=10, maximum_titles=100000,
                           maximum_scan_seconds=3600, favorites_trigger_keep=True,
                           timer=monotonic):
    """Fully collect all libraries, then use the existing decision parity bridge.

    A returned plan is advisory: execution must refresh protections, validate
    source/destination/revision and persist intent. No operation can be authorized
    by setting LibraryScan.complete or by supplying this return value.
    """
    if type(revision) is not int or revision < 0:
        raise ValueError('A nonnegative tracking revision is required')
    if not isinstance(now, datetime) or now.tzinfo is not None:
        raise ValueError('Existing lifecycle clocks require naive local scan time')
    if not isinstance(libraries, (tuple, list)) or not libraries or any(
            not isinstance(name, str) or not name for name in libraries):
        raise ValueError('Explicit configured libraries are required')
    libraries = tuple(libraries)
    if len(set(libraries)) != len(libraries):
        raise ValueError('Duplicate configured library')
    if (type(maximum_actions) is not int or not 1 <= maximum_actions <= 100000
            or type(maximum_titles) is not int or not 1 <= maximum_titles <= 100000):
        raise ValueError('Positive bounded action/title caps required')
    if (type(maximum_scan_seconds) not in (int, float)
            or not math.isfinite(maximum_scan_seconds) or maximum_scan_seconds <= 0
            or type(favorites_trigger_keep) is not bool):
        raise ValueError('Invalid scan policy')
    detached = deepcopy(snapshot)
    validate_snapshot(detached)
    if detached.get(INTENTS_KEY):
        raise ScheduledScanBlocked('unresolved_sqlite_operation')
    started = timer()

    def check_time():
        elapsed = timer() - started
        if not math.isfinite(elapsed) or elapsed < 0 or elapsed >= maximum_scan_seconds:
            raise ScheduledScanBlocked('scan_deadline_exceeded')

    collected, keys = [], set()
    for library in libraries:
        check_time()
        scan = scan_library(library)
        check_time()
        if not isinstance(scan, LibraryScan) or scan.complete is not True:
            raise ScheduledScanBlocked('library_scan_incomplete')
        for title in scan.titles:
            check_time()
            if len(collected) >= maximum_titles:
                raise ScheduledScanBlocked('scan_title_limit_exceeded')
            if (not isinstance(title, ScannedTitle) or not isinstance(title.media_key, str)
                    or not title.media_key or not isinstance(title.stage, str) or title.stage not in CLOCKS
                    or type(title.threshold_days) is not int or title.threshold_days < 0):
                raise ScheduledScanBlocked('invalid_title_observation')
            if title.media_key in keys:
                raise ScheduledScanBlocked('duplicate_media_identity')
            if title.signals is not None and (not isinstance(title.signals, dict) or any(
                    type(value) is not bool for value in title.signals.values())):
                raise ScheduledScanBlocked('invalid_protection_signals')
            keys.add(title.media_key)
            collected.append((library, deepcopy(title)))
    check_time()
    # No decision is calculated until every collector and iterator has completed.
    from app.sqlite_scan_details import LIMIT, reason_code
    moves, skipped, capped = [], [], 0
    observations=[]
    for library, title in collected:
        check_time()
        decision = review_decision(detached, title.media_key, title.stage, now,
                                   title.threshold_days, title.signals, favorites_trigger_keep)
        destination = _DESTINATIONS.get((title.stage, decision['action']))
        outcome='skipped' if destination is None else 'capped' if len(moves)>=maximum_actions else 'planned'
        observation=(library,title.media_key,title.stage,destination,
            'action_cap' if outcome=='capped' else reason_code(decision),outcome)
        if len(observations)<LIMIT:
            observations.append(observation)
        elif outcome=='planned':
            # Keep selected moves visible even when many earlier titles stay put.
            replace_index=next((index for index in range(len(observations)-1,-1,-1)
                if observations[index][-1]!='planned'),None)
            if replace_index is not None:observations[replace_index]=observation
        if destination is None:
            skipped.append((library, title.media_key, tuple(decision['blockers']), decision['action']))
        elif len(moves) >= maximum_actions:
            capped += 1
        else:
            moves.append(PlannedMove(library, title.media_key, title.stage, destination,
                decision['action'], detached[CLOCKS[title.stage]][title.media_key], title.threshold_days))
    check_time()
    return ScheduledPlan(revision, now, libraries, len(collected), tuple(moves), tuple(skipped), capped,
                         favorites_trigger_keep, started, started + maximum_scan_seconds, os.getpid(), title_observations=tuple(observations))
