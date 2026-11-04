"""Descriptor-checked inventory plus GET-only JSON rehearsal; never checkpoints.

Missing/new TV clocks are proposals for review, not inferred old dates or move
permission. No entrypoint selects this module for a live worker.
"""
from contextlib import ExitStack, nullcontext
from copy import deepcopy
from datetime import datetime
import os
from pathlib import Path
import stat
from time import monotonic
import math
import posixpath
from zoneinfo import ZoneInfo

from app.json_scan_collection import InventoryTitle, LibraryInventory, collect_readonly_plan
from app.json_tracking_store import JsonTrackingStore
from app.json_lifecycle_plan import LibraryObservation, plan_scan
from app.lifecycle_stages import CLOCKS
from app.content_observation import observe_scheduled_content, ScheduledContentBlocked
from app.filesystem_paths import _canonical, _open_directory, scan_held_directory
from app.title_identity import validate_title_folder


def _bool(values,key,default):
    value = values.get(key,default)
    if isinstance(value,str): value = value.strip().lower()
    if value not in ('true','false'): raise ValueError('Explicit boolean setting required')
    return value == 'true'


def _days(values,key,default):
    raw = values.get(key,default)
    if isinstance(raw,str): raw = raw.strip()
    if not isinstance(raw,str) or not raw.isascii() or not raw.isdecimal() or not 0 <= int(raw) <= 100000:
        raise ValueError('Bounded lifecycle duration required')
    return int(raw)


def _identity(info):
    return info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns


def rehearse_scan(*, state_file, settings, now=None, maximum_titles=100000,
                   collect=collect_readonly_plan, timer=monotonic, maximum_seconds=3600,
                   observer=lambda stage: None):
    """Read-only public rehearsal; never opens a checkpoint-capable worker mode."""
    return _scan(state_file=state_file, settings=settings, now=now,
        maximum_titles=maximum_titles, collect=collect, timer=timer,
        maximum_seconds=maximum_seconds, observer=observer)


def collect_worker_scan(session, *, settings, **kwargs):
    """Collect under the worker's existing exclusive session and save fresh clocks.

    This only updates discovery/content dates; moves remain a separate executor.
    The caller owns admission and holds the same session throughout collection.
    """
    session.verify()
    return _scan(state_file=str(session._path), settings=settings,
                 _session=session, _save_clocks=True, **kwargs)


def _scan(*, state_file, settings, now=None, maximum_titles=100000,
                   collect=collect_readonly_plan, timer=monotonic, maximum_seconds=3600, observer=lambda stage: None,
                   _session=None, _save_clocks=False):
    values = deepcopy(settings)
    zone_name = values.get('DAILY_RUN_TIMEZONE') or values.get('TZ') or 'UTC'
    zone = ZoneInfo(zone_name)
    now = datetime.now(zone).replace(tzinfo=None) if now is None else now
    if not isinstance(now,datetime) or now.tzinfo is not None:
        raise ValueError('Naive lifecycle observation time required')
    if type(maximum_titles) is not int or not 1 <= maximum_titles <= 100000:
        raise ValueError('Bounded total inventory required')
    if (type(maximum_seconds) not in (int,float) or not math.isfinite(maximum_seconds)
            or not 0 < maximum_seconds <= 3600):
        raise ValueError('Bounded rehearsal deadline required')
    started = timer()
    def remaining():
        elapsed = timer()-started
        if not math.isfinite(elapsed) or not 0 <= elapsed < maximum_seconds:
            raise RuntimeError('Rehearsal deadline exceeded')
        return maximum_seconds-elapsed
    reset_tv = _bool(values,'TV_NEW_EPISODES_RESET_CLOCK','true')
    base = _canonical(values.get('MEDIA_PATH','/media').strip())
    holding = _days(values,'HOLDING_DAYS','7')
    removal = _days(values,'REMOVAL_DAYS','7')
    definitions, all_paths = [], []
    private = Path(state_file)
    for name,prefix,enabled,wait in (('Movies','RADARR','ENABLE_MOVIES','MOVIE_WAIT_DAYS'),
                                   ('TV','SONARR','ENABLE_TV','TV_WAIT_DAYS')):
        if not _bool(values,enabled,'true' if name == 'Movies' else 'false'): continue
        local, remote = {}, {}
        for stage,field in (('Waiting','TRANSIENT'),('Holding','HOLDING'),('Keep','KEEP'),('Removal','REMOVAL')):
            explicit = values.get(prefix+'_'+field+'_PATH','')
            if not isinstance(explicit,str): raise ValueError('String stage path required')
            suffix = {'Waiting':'','Holding':'_hold','Keep':'_keep','Removal':'_removal'}[stage]
            path = _canonical(explicit.strip() or posixpath.join(base,name+suffix))
            current = Path(path)
            if current == Path('/') or current == private or current in private.parents or private in current.parents:
                raise ValueError('Disjoint dedicated media roots required')
            if any(current == other or current in other.parents or other in current.parents for other in all_paths):
                raise ValueError('Distinct nonoverlapping media stages required')
            all_paths.append(current); local[stage] = path
            override = values.get(prefix+'_APP_'+stage.upper()+'_PATH','') if stage != 'Waiting' else ''
            remote[stage] = _canonical(override or path)
        definitions.append((name,local,remote,_days(values,wait,'30' if name == 'Movies' else '60')))
    if not definitions: raise ValueError('At least one library required')
    observer('tracking_validation')
    with (JsonTrackingStore(state_file).session() if _session is None else nullcontext(_session)) as session, ExitStack() as stack:
        snapshot = deepcopy(session.state)
        plan_scan(snapshot=snapshot,libraries=[LibraryObservation(name,False,False,())
            for name,_,_,_ in definitions],now=now,maximum_titles=maximum_titles)
        roots, stage_rows, ignored, seen_root, content_times, seen_titles = {}, {}, {}, set(), {}, set()
        def inventory(fd):
            rows, excluded = {}, 0
            with scan_held_directory(fd) as entries:
                for entry in entries:
                    remaining()
                    info = entry.stat(follow_symlinks=False)
                    if ((entry.name == '.DS_Store' and stat.S_ISREG(info.st_mode))
                            or (entry.name == '.deletedByTMM' and stat.S_ISDIR(info.st_mode))):
                        excluded += 1; continue
                    validate_title_folder(entry.name)
                    if entry.name.startswith('.') or not stat.S_ISDIR(info.st_mode):
                        raise RuntimeError('Unsupported stage entry')
                    if len(rows) >= maximum_titles: raise RuntimeError('Inventory limit exceeded')
                    rows[entry.name] = _identity(info)
            return rows, excluded
        observer('local_inventory')
        inventories, clock_proposals, inventory_issues, total = [], [], [], 0
        for name,local,remote,wait in definitions:
            complete, titles, seen_keys = True, [], set()
            for stage,path in local.items():
                remaining()
                try:
                    fd = _open_directory(path); stack.callback(os.close,fd)
                    info = os.fstat(fd)
                    if (info.st_dev,info.st_ino) in seen_root:
                        raise ValueError('Aliased stage roots')
                    seen_root.add((info.st_dev,info.st_ino))
                    roots[name,stage] = fd,path,_identity(info)
                    rows, excluded = inventory(fd)
                    stage_rows[name,stage] = rows; ignored[name,stage] = excluded
                    for folder,identity in sorted(rows.items()):
                        key = ('TV/' if name == 'TV' else '')+folder
                        remaining()
                        if key in seen_keys:
                            raise RuntimeError('Ambiguous title stage')
                        if identity[:2] in seen_titles:
                            raise ValueError('Aliased title directories')
                        seen_keys.add(key); seen_titles.add(identity[:2])
                        total += 1
                        if total > maximum_titles: raise ValueError('Total inventory limit exceeded')
                        blocker = None
                        sections = [section for section in CLOCKS.values() if key in snapshot[section]]
                        if not sections:
                            blocker = 'discovery_required'
                            clock_proposals.append({'library':name,'title':folder,'stage':stage,
                                'reason':'discovery_required','previous':None,'proposed':now.isoformat()})
                        if name == 'TV' and stage == 'Waiting' and reset_tv:
                            try:
                                newest = observe_scheduled_content(title_path=path+'/'+folder,now=now,
                                    maximum_seconds=min(30,remaining()),timer=timer,timezone_info=zone)
                                content_times[path+'/'+folder] = newest
                                if newest is not None and sections == [CLOCKS[stage]] and newest > datetime.fromisoformat(snapshot[CLOCKS[stage]][key]):
                                    blocker = 'content_reset_required'
                                    clock_proposals.append({'library':name,'title':folder,'stage':stage,
                                        'reason':blocker,'previous':snapshot[CLOCKS[stage]][key], 'proposed':newest.isoformat()})
                            except ScheduledContentBlocked as error:
                                blocker = 'future_content_timestamp' if str(error) == 'future_content_timestamp' else 'content_unavailable'
                                clock_proposals[:] = [row for row in clock_proposals if not (row['library'] == name and row['title'] == folder)]
                        titles.append(InventoryTitle(folder,stage,wait if stage == 'Waiting' else
                            holding if stage == 'Holding' else removal,blocker))
                except (OSError,RuntimeError) as error:
                    complete = False
                    reason = {'Unsupported stage entry':'unsupported_stage_entry',
                        'Ambiguous title stage':'ambiguous_title_stage',
                        'Inventory limit exceeded':'inventory_limit_exceeded'}.get(
                        str(error),'stage_unavailable_or_changed')
                    inventory_issues.append({'library':name,'stage':stage,'reason':reason})
            inventories.append(LibraryInventory(name,tuple(remote.items()),tuple(titles),complete))
        def verify_inventory():
            remaining()
            session.verify()
            for key,(fd,path,initial) in roots.items():
                reopened = _open_directory(path)
                try:
                    if _identity(os.fstat(reopened)) != initial:
                        raise RuntimeError('Stage changed during rehearsal')
                finally: os.close(reopened)
                if key in stage_rows and inventory(fd) != (stage_rows[key],ignored[key]):
                    raise RuntimeError('Inventory changed during rehearsal')
            for path,newest in content_times.items():
                if observe_scheduled_content(title_path=path,now=now,maximum_seconds=min(30,remaining()),timer=timer,timezone_info=zone) != newest:
                    raise RuntimeError('TV content changed during rehearsal')
        verify_inventory()
        changed_dates = 0
        if _save_clocks:
            from app.json_clock_updates import ClockObservation, apply_clock_observations
            complete_libraries = {item.library for item in inventories if item.complete}
            changes = tuple(ClockObservation(
                ('TV/' if row['library'] == 'TV' else '')+row['title'],row['stage'],
                row['previous'],datetime.fromisoformat(row['proposed']),
                'discovered' if row['reason'] == 'discovery_required' else 'content_reset')
                for row in clock_proposals if row['library'] in complete_libraries)
            def verify_clock(change):
                library = 'TV' if change.media_key.startswith('TV/') else 'Movies'
                folder = change.media_key[3:] if library == 'TV' else change.media_key
                fd,path,initial = roots[library,change.stage]
                reopened = _open_directory(path)
                try:
                    if _identity(os.fstat(reopened)) != initial:
                        return False
                finally: os.close(reopened)
                if _identity(os.stat(folder,dir_fd=fd,follow_symlinks=False)) != stage_rows[library,change.stage][folder]:
                    return False
                content_path = path+'/'+folder
                if content_path in content_times:
                    return observe_scheduled_content(title_path=content_path,now=now,
                        maximum_seconds=min(30,remaining()),timer=timer,timezone_info=zone) == content_times[content_path]
                return True
            changed_dates = apply_clock_observations(session,changes=changes,now=now,
                verify_change=verify_clock)['changed_dates']
            snapshot = deepcopy(session.state)
            # Rebuild local blockers against the newly recorded clocks. Service reads
            # use this snapshot, so they cannot move using a superseded TV clock.
            applied = {change.media_key for change in changes}
            inventories = [LibraryInventory(item.library,item.roots,tuple(
                InventoryTitle(title.folder,title.stage,title.threshold_days,
                    None if ('TV/' if item.library == 'TV' else '')+title.folder in applied else title.blocker)
                for title in item.titles),item.complete) for item in inventories]
            verify_inventory()
        observer('service_collection')
        result = collect(snapshot=snapshot,inventories=tuple(inventories),settings=values,
            now=now,maximum_titles=maximum_titles,maximum_seconds=remaining(),timer=timer)
        observer('inventory_revalidation')
        verify_inventory()
        return {**result,'comparison_only':not _save_clocks, 'clock_proposals':tuple(clock_proposals),
            'ignored_housekeeping_entries':sum(ignored.values()),'tracking_modified':bool(changed_dates),'clock_changes_applied':changed_dates,
            'inventory_issues':tuple(inventory_issues),
            'inventory_checked_before_and_after':True,
            'inventory_independently_verified':False,'external_writers_excluded':False,'lifecycle_timezone':zone_name}
