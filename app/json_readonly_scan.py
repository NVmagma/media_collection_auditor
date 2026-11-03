"""Descriptor-checked inventory plus GET-only JSON rehearsal; never checkpoints.

Missing/new TV clocks are proposals for review, not inferred old dates or move
permission. No entrypoint selects this module for a live worker.
"""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime
import os
from pathlib import Path
import stat
from time import monotonic
import math

from app.json_scan_collection import InventoryTitle, LibraryInventory, collect_readonly_plan
from app.json_tracking_store import JsonTrackingStore
from app.json_lifecycle_plan import LibraryObservation, plan_scan
from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_scheduled_content import observe_scheduled_content, ScheduledContentBlocked
from app.sqlite_scheduled_paths import _canonical, _open_directory, scan_held_directory
from app.sqlite_title_identity import validate_title_folder


def _bool(values,key,default):
    value = values.get(key,default)
    if value not in ('true','false'): raise ValueError('Explicit boolean setting required')
    return value == 'true'


def _days(values,key,default):
    raw = values.get(key,default)
    if not isinstance(raw,str) or not raw.isascii() or not raw.isdecimal() or not 0 <= int(raw) <= 100000:
        raise ValueError('Bounded lifecycle duration required')
    return int(raw)


def _identity(info):
    return info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns


def rehearse_scan(*, state_file, settings, now=None, maximum_titles=100000,
                   collect=collect_readonly_plan, timer=monotonic, maximum_seconds=3600):
    now = datetime.now() if now is None else now
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
    values = deepcopy(settings)
    reset_tv = _bool(values,'TV_NEW_EPISODES_RESET_CLOCK','true')
    holding = _days(values,'HOLDING_DAYS','7')
    removal = _days(values,'REMOVAL_DAYS','7')
    definitions, all_paths = [], []
    private = Path(state_file)
    for name,prefix,enabled,wait in (('Movies','RADARR','ENABLE_MOVIES','MOVIE_WAIT_DAYS'),
                                   ('TV','SONARR','ENABLE_TV','TV_WAIT_DAYS')):
        if not _bool(values,enabled,'true' if name == 'Movies' else 'false'): continue
        local, remote = {}, {}
        for stage,field in (('Waiting','TRANSIENT'),('Holding','HOLDING'),('Keep','KEEP'),('Removal','REMOVAL')):
            path = _canonical(values.get(prefix+'_'+field+'_PATH',''))
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
    with JsonTrackingStore(state_file).session() as session, ExitStack() as stack:
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
                                    maximum_seconds=min(30,remaining()),timer=timer)
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
                if observe_scheduled_content(title_path=path,now=now,maximum_seconds=min(30,remaining()),timer=timer) != newest:
                    raise RuntimeError('TV content changed during rehearsal')
        verify_inventory()
        result = collect(snapshot=snapshot,inventories=tuple(inventories),settings=values,
            now=now,maximum_titles=maximum_titles,maximum_seconds=remaining(),timer=timer)
        verify_inventory()
        return {**result,'comparison_only':True, 'clock_proposals':tuple(clock_proposals),
            'ignored_housekeeping_entries':sum(ignored.values()),'tracking_modified':False,
            'inventory_issues':tuple(inventory_issues),
            'inventory_checked_before_and_after':True,
            'inventory_independently_verified':False,'external_writers_excluded':False}
