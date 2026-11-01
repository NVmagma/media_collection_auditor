"""Read-only production configuration/inventory boundary for scheduled SQLite.

Consumes the existing build_libraries() shape without importing the production
worker (whose imports initialize clients). No persistence, move dispatch, Arr
calls or backend activation. Root descriptors remain held through the entire
collection barrier. External writers are not excluded.
"""
from copy import deepcopy
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import datetime
import math
import os
from pathlib import PurePosixPath
import stat
from time import monotonic

from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_run_schedule import DailyRunSchedule
from app.sqlite_scheduled_paths import _canonical, _open_directory, scan_held_directory
from app.sqlite_scheduled_plan import LibraryScan, ScannedTitle, ScheduledScanBlocked, collect_scheduled_plan
from app.sqlite_state import validate_snapshot
from app.sqlite_title_identity import validate_title_folder

_STAGE_FIELDS = (('Waiting', 'transient'), ('Holding', 'holding'),
                 ('Keep', 'keep'), ('Removal', 'removal'))


@dataclass(frozen=True)
class ScheduledLibrary:
    name: str
    jellyfin_type: str
    state_prefix: str
    roots: tuple
    wait_days: int
    holding_days: int
    new_content_resets_clock: bool = False

    def media_key(self, folder):
        return self.state_prefix + validate_title_folder(folder)


@dataclass(frozen=True)
class ScheduledWorkerConfig:
    schedule: DailyRunSchedule
    libraries: tuple
    maximum_actions: int
    favorites_trigger_keep: bool
    maximum_actions_per_library: int | None = None


@dataclass(frozen=True)
class ScheduledTitleBinding:
    library: str
    media_key: str
    folder: str
    stage: str
    jellyfin_type: str


@dataclass(frozen=True)
class ScheduledWorkerPreparation:
    plan: object
    bindings: tuple
    untracked: tuple
    clock_proposal: object = None
    root_bindings: tuple = ()
    title_identities: tuple = ()
    configuration: object = None
    production_authorized: bool = False
    production_activation: str = 'disabled'


def configured_scheduled_worker(*, libraries, local_time, timezone_name,
                                holding_days, maximum_actions=10,
                                favorites_trigger_keep=True):
    """Detach only supported settings from the current library dictionaries.

    Arr clients/credentials are neither retained nor invoked. Whole-show moves
    do not prune seasons. Episode-driven resets require discovery preparation;
    the ordinary planning path refuses that policy instead of ignoring it.
    """
    schedule = DailyRunSchedule(local_time, timezone_name)
    if (type(maximum_actions) is not int or not 1 <= maximum_actions <= 100000
            or type(holding_days) is not int or holding_days < 0
            or type(favorites_trigger_keep) is not bool
            or not isinstance(libraries, (list, tuple)) or not libraries):
        raise ValueError('Explicit bounded scheduled worker policy required')
    captured, names, prefixes, paths = [], set(), set(), []
    for library in libraries:
        if not isinstance(library, dict):
            raise ValueError('Configured library dictionary required')
        name, kind, prefix = (library.get(field) for field in ('name', 'jellyfin_type', 'state_prefix'))
        if (not isinstance(name, str) or not name.strip() or name in names
                or kind not in ('Movie', 'Series')
                or prefix != ('' if kind == 'Movie' else 'TV/') or prefix in prefixes
                or type(library.get('wait_days')) is not int or library['wait_days'] < 0):
            raise ValueError('Unique library/type/tracking binding required')
        reset_clock = library.get('new_content_resets_clock', False)
        if type(reset_clock) is not bool or (reset_clock and kind != 'Series'):
            raise ValueError('Explicit series-only new-content policy required')
        roots = tuple((stage, _canonical(library.get(field))) for stage, field in _STAGE_FIELDS)
        paths.extend(PurePosixPath(path) for _, path in roots)
        captured.append(ScheduledLibrary(name, kind, prefix, roots, library['wait_days'], holding_days, reset_clock))
        names.add(name); prefixes.add(prefix)
    if any(a == b or a in b.parents or b in a.parents
           for i, a in enumerate(paths) for b in paths[i + 1:]):
        raise ValueError('Configured libraries require disjoint stage roots')
    return ScheduledWorkerConfig(schedule, tuple(captured), maximum_actions, favorites_trigger_keep)


def prepare_scheduled_worker(*, config, snapshot, revision, fetch_signals,
                             now=None, maximum_titles=100000,
                             maximum_scan_seconds=3600, timer=monotonic, discover_clocks=False):
    """Inventory all four roots in every library, then return one bounded plan.

    fetch_signals receives an immutable title binding and must perform bounded,
    read-only authoritative collection. Missing protection yields no candidate;
    an exception or changed inventory aborts the whole preparation. Untracked
    titles are reported, never assigned clocks or moved. No on-disk paths or
    evidence in this result confer permission for a subsequent operation.
    """
    if not isinstance(config, ScheduledWorkerConfig) or not callable(fetch_signals):
        raise ValueError('Scheduled worker configuration and protection reader required')
    if type(discover_clocks) is not bool or (not discover_clocks and any(
            library.new_content_resets_clock for library in config.libraries)):
        raise ValueError('TV content policy requires discovery preparation')
    if (type(maximum_titles) is not int or not 1 <= maximum_titles <= 100000
            or type(maximum_scan_seconds) not in (int, float)
            or not math.isfinite(maximum_scan_seconds) or maximum_scan_seconds <= 0):
        raise ValueError('Bounded scan policy required')
    snapshot = deepcopy(snapshot)
    validate_snapshot(snapshot)
    if snapshot.get(INTENTS_KEY):
        raise ScheduledScanBlocked('unresolved_sqlite_operation')
    now = datetime.now() if now is None else now
    if not isinstance(now, datetime) or now.tzinfo is not None:
        raise ValueError('Naive local lifecycle time required')
    start = timer()
    def check_time():
        elapsed = timer() - start
        if not math.isfinite(elapsed) or not 0 <= elapsed < maximum_scan_seconds:
            raise ScheduledScanBlocked('scan_deadline_exceeded')
    bindings, inventories, handles, identities = [], {}, {}, set()
    stage_metadata = {}
    def metadata(info):
        return info.st_mtime_ns, info.st_ctime_ns, info.st_size
    with ExitStack() as stack:
        # Pin all configured roots before any external collection, including
        # identity aliases that lexical path checks cannot discover.
        for library in config.libraries:
            for stage, path in library.roots:
                check_time()
                fd = _open_directory(path)
                stack.callback(os.close, fd)
                info = os.fstat(fd); identity = (info.st_dev, info.st_ino)
                if identity in identities:
                    raise ScheduledScanBlocked('aliased_library_stage_roots')
                identities.add(identity)
                handles[library.name, stage] = (fd, path, identity)
                stage_metadata[library.name, stage] = metadata(info)
        def inventory(fd):
            rows = {}
            with scan_held_directory(fd) as entries:
                for entry in entries:
                    check_time()
                    validate_title_folder(entry.name)
                    info = entry.stat(follow_symlinks=False)
                    # Finder metadata is not a title. Never follow a symlink
                    # or extend this exception to arbitrary hidden entries.
                    if entry.name == ".DS_Store" and stat.S_ISREG(info.st_mode):
                        continue
                    if not stat.S_ISDIR(info.st_mode):
                        raise ScheduledScanBlocked('non_directory_or_symlink_in_stage')
                    if len(rows) >= maximum_titles:
                        raise ScheduledScanBlocked('scan_title_limit_exceeded')
                    rows[entry.name] = (info.st_dev, info.st_ino)
            return rows
        seen_keys, seen_titles = set(), set()
        for library in config.libraries:
            for stage, _ in library.roots:
                rows = inventory(handles[library.name, stage][0])
                inventories[library.name, stage] = rows
                for folder, identity in sorted(rows.items()):
                    key = library.media_key(folder)
                    if key in seen_keys or identity in seen_titles:
                        raise ScheduledScanBlocked('ambiguous_title_location')
                    if len(bindings) >= maximum_titles:
                        raise ScheduledScanBlocked('scan_title_limit_exceeded')
                    seen_keys.add(key); seen_titles.add(identity)
                    bindings.append(ScheduledTitleBinding(library.name, key, folder, stage, library.jellyfin_type))
        def verify_inventory():
            for identity_key, (fd, path, identity) in handles.items():
                check_time()
                reopened = _open_directory(path)
                try:
                    info = os.fstat(reopened)
                    if (info.st_dev, info.st_ino) != identity:
                        raise ScheduledScanBlocked('configured_stage_changed')
                    if metadata(info) != stage_metadata[identity_key]:
                        raise ScheduledScanBlocked('configured_stage_contents_changed')
                finally:
                    os.close(reopened)
                if inventory(fd) != inventories[identity_key]:
                    raise ScheduledScanBlocked('title_inventory_changed')
                if metadata(os.fstat(fd)) != stage_metadata[identity_key]:
                    raise ScheduledScanBlocked('configured_stage_contents_changed')
        begin_scan = getattr(fetch_signals, 'begin_scan', None)
        if callable(begin_scan):
            begin_scan()
        by_name = {library.name: library for library in config.libraries}
        available_keys, content_times = set(), {}
        future_content_keys = set()
        def scan(name):
            library = by_name[name]
            def titles():
                for binding in bindings:
                    if binding.library == name:
                        check_time()
                        signals = fetch_signals(binding)
                        check_time()
                        if discover_clocks:
                            fields = ('played', 'favorite', 'disliked', 'keep', 'keep_all', 'protected')
                            if not isinstance(signals, dict) or not all(type(signals.get(field)) is bool for field in fields):
                                signals = None
                            else:
                                available_keys.add(binding.media_key)
                                if library.new_content_resets_clock and binding.stage == 'Waiting':
                                    from app.sqlite_scheduled_content import (observe_scheduled_content,
                                        ScheduledContentBlocked)
                                    try:
                                        content_times[binding.media_key] = observe_scheduled_content(
                                            title_path=dict(library.roots)[binding.stage] + '/' + binding.folder,
                                            now=now, maximum_seconds=min(30, maximum_scan_seconds - (timer() - start)),
                                            timer=timer)
                                    except ScheduledContentBlocked as error:
                                        if str(error) != 'future_content_timestamp':
                                            raise
                                        # Never reuse this title's old clock or protection to
                                        # authorize a move after an invalid content observation.
                                        future_content_keys.add(binding.media_key)
                                        available_keys.discard(binding.media_key)
                                        signals = None
                        check_time()
                        yield ScannedTitle(binding.media_key, binding.stage,
                            library.wait_days if binding.stage == 'Waiting' else library.holding_days,
                            signals)
            return LibraryScan(True, titles())
        # Pass only the remaining total budget to the existing collection barrier.
        check_time()
        remaining = maximum_scan_seconds - (timer() - start)
        plan = collect_scheduled_plan(snapshot=snapshot, revision=revision,
            libraries=tuple(by_name), scan_library=scan, now=now,
            maximum_actions=config.maximum_actions, maximum_titles=maximum_titles,
            maximum_actions_per_library=config.maximum_actions_per_library,
            maximum_scan_seconds=remaining, favorites_trigger_keep=config.favorites_trigger_keep,
            timer=timer)
        if future_content_keys:
            if any(move.media_key in future_content_keys for move in plan.moves):
                raise ScheduledScanBlocked('invalid_content_candidate')
            plan = replace(plan,
                skipped=tuple((library, key, ('future_content_timestamp',), 'none')
                    if key in future_content_keys else (library, key, blockers, action)
                    for library, key, blockers, action in plan.skipped),
                title_observations=tuple((library, key, stage, None, 'future_content_timestamp', 'skipped')
                    if key in future_content_keys else (library, key, stage, destination, reason, outcome)
                    for library, key, stage, destination, reason, outcome in plan.title_observations))
        proposal = None
        if discover_clocks:
            from app.sqlite_scheduled_discovery import propose_discovery_clocks
            proposal = propose_discovery_clocks(snapshot=snapshot, revision=revision,
                bindings=bindings, now=now, available_protection_keys=available_keys,
                reset_keys=set(content_times), reset_content_times=content_times)
            if proposal.changes:
                # The clocks have NOT been checkpointed. Nothing from the old
                # plan may execute; the future worker must CAS then rebuild.
                plan = replace(plan, moves=(), capped_moves=0, skipped=plan.skipped +
                    tuple((move.library, move.media_key, ('discovery_checkpoint_required',), 'none')
                          for move in plan.moves))
        verify_inventory()
        untracked = tuple(binding.media_key for binding in bindings
            if not any(binding.media_key in snapshot[clock] for clock in CLOCKS.values()))
        return ScheduledWorkerPreparation(plan, tuple(bindings), untracked, proposal,
            root_bindings=tuple((name, stage, path, identity) for (name, stage), (_, path, identity) in handles.items()),
            title_identities=tuple((binding.media_key, inventories[binding.library, binding.stage][binding.folder])
                                   for binding in bindings), configuration=config)
