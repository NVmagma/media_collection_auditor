"""Read service data for the JSON scan planner without changing tracking or media.

The caller supplies the local inventory and is responsible for checking it.
Nothing here approves a move, reserves a scan slot, or saves state.
"""
from copy import deepcopy
from app.scan_progress import emit
from dataclasses import dataclass
from time import monotonic
import math

from app.json_lifecycle_plan import LibraryObservation, TitleObservation, plan_scan
from app.arr_catalog import ArrCatalogGET, catalog_paths_by_folder
from app.jellyfin_collection import collect_title_observation, validated_tag_names
from app.jellyfin_scan_cache import _ScanCatalog
from app.filesystem_paths import _canonical
from app.jellyfin_transport import ScheduledJellyfinGET
from app.tv_season_policy import ARCHIVE
from app.lifecycle_decisions import decide
from app.media_libraries import is_tv_library, media_key_for


@dataclass(frozen=True)
class InventoryTitle:
    folder: str
    stage: str
    threshold_days: int
    blocker: str | None = None


@dataclass(frozen=True)
class LibraryInventory:
    library: str
    roots: tuple  # Use the stage paths Arr sees, including any configured aliases.
    titles: tuple
    complete: bool
    media_type: str | None = None


def collect_readonly_plan(*, snapshot, inventories, settings, now,
        jellyfin_factory=ScheduledJellyfinGET, arr_factory=ArrCatalogGET,
        timer=monotonic, maximum_seconds=3600, maximum_titles=100000):
    if (not isinstance(inventories, (tuple,list)) or not 1 <= len(inventories) <= 2
            or not isinstance(settings, dict) or type(maximum_seconds) not in (int,float)
            or not math.isfinite(maximum_seconds) or not 0 < maximum_seconds <= 3600):
        raise ValueError('Explicit bounded collection required')
    snapshot, inventories, settings = deepcopy((snapshot, inventories, settings))
    raw_limit=settings.get('JSON_PER_LIBRARY_ACTION_LIMIT','1')
    if not isinstance(raw_limit,str) or raw_limit not in ('1','2','3','4','5'):
        raise ValueError('Bounded per-library action limit required')
    per_library_limit=int(raw_limit)
    start = timer()
    def check_deadline():
        elapsed = timer()-start
        if not math.isfinite(elapsed) or not 0 <= elapsed < maximum_seconds:
            raise RuntimeError('Read-only collection deadline exceeded')
    # Check the IDs and captured state before contacting a service.
    prelim, roots = [], {}
    for inventory in inventories:
        if (not isinstance(inventory, LibraryInventory) or type(inventory.complete) is not bool
                or not isinstance(inventory.titles, tuple) or not isinstance(inventory.roots, tuple)):
            raise ValueError('Explicit local inventory required')
        mapping = dict(inventory.roots)
        if len(mapping) != len(inventory.roots) or set(mapping) != {'Waiting','Holding','Keep','Removal'}:
            raise ValueError('Unique stage roots required')
        for path in mapping.values():
            if _canonical(path) == '/': raise ValueError('Dedicated stage roots required')
        if len(set(mapping.values())) != 4: raise ValueError('Distinct stage roots required')
        roots[inventory.library] = mapping
        titles = []
        for title in inventory.titles:
            if not isinstance(title, InventoryTitle): raise ValueError('Known title binding required')
            key = media_key_for(inventory.library, title.folder, inventory.media_type)
            titles.append(TitleObservation(key,title.stage,title.threshold_days,None,'unavailable',title.blocker))
        prelim.append(LibraryObservation(inventory.library,False,False,tuple(titles)))
    plan_scan(snapshot=snapshot,libraries=prelim,now=now,maximum_titles=maximum_titles)
    tags = validated_tag_names({name:settings.get(key, default) for name,key,default in (
        ('keep','KEEP_TAG','keep'), ('disliked','DISLIKE_TAG','not-at-all'),
        ('keep_all','KEEP_ALL_SEASONS_TAG','keep-all-seasons'), ('protected','PROTECT_TAG','keep-forever'))})
    favorites = settings.get('FAVORITES_TRIGGER_KEEP','true')
    if isinstance(favorites,str): favorites = favorites.strip().lower()
    if favorites not in ('true','false'): raise ValueError('Explicit favorites policy required')
    total_titles=sum(len(inventory.titles) for inventory in inventories)
    checked=0
    observations, collection_status = [], []
    season_titles, season_policy_titles = set(), set()
    season_enabled = settings.get('ENABLE_TV_SEASON_RETENTION', 'false') == 'true'
    for inventory, preliminary in zip(inventories,prelim,strict=True):
        check_deadline()
        jf_complete = arr_complete = False
        signals = {}
        absence = {}
        catalog = {}
        emit('jellyfin',checked=checked,total=total_titles,library=inventory.library)
        if inventory.complete and inventory.titles:
            try:
                fetch = jellyfin_factory(base_url=settings.get('JELLYFIN_HOST_URL',''),
                    token=settings.get('JELLYFIN_API_TOKEN',''))
                cached = _ScanCatalog(fetch)
                jf_complete = True
                jf_checked = False
                for title, initial in zip(inventory.titles,preliminary.titles,strict=True):
                    check_deadline()
                    emit('jellyfin',checked=checked,total=total_titles,library=inventory.library)
                    if title.blocker is not None and title.blocker not in ('no_video','future_content_timestamp'):
                        checked+=1
                        emit('jellyfin',checked=checked,total=total_titles,library=inventory.library)
                        continue
                    jf_checked = True
                    season_args = {}
                    if is_tv_library(inventory.library, inventory.media_type) and season_enabled:
                        from app.tv_season_review import season_holding_root
                        if any(key.startswith(initial.media_key + '/') for key in snapshot.get(ARCHIVE, {})):
                            season_args['excluded_series_path'] = str(season_holding_root(settings) / title.folder)
                    result = collect_title_observation(fetch=cached,
                        jellyfin_type='Series' if is_tv_library(inventory.library, inventory.media_type) else 'Movie',
                        folder=title.folder,media_key=initial.media_key,now=now,tag_names=tags,**season_args)
                    if (is_tv_library(inventory.library, inventory.media_type) and season_enabled
                            and result['status'] == 'shape_valid_untrusted'
                            and (season_args or 'one-season' in (result.get('observed_tags') or ()))):
                        # Restore staged seasons first, but do not let one-season hide a Keep rescue.
                        action, _ = decide(title.stage, None, title.threshold_days,
                                           result['signals'], favorites == 'true')
                        if title.blocker != 'future_content_timestamp' or season_args and result['signals']['keep_all']:
                            if season_args or title.stage in ('Waiting', 'Keep') and action not in ('keep', 'rescue'):
                                season_policy_titles.add(title.folder)
                            if season_args or title.stage in ('Waiting', 'Keep'):
                                season_titles.add(title.folder)
                    if 'jellyfin_collection_incomplete' in result['blockers']:
                        jf_complete = False
                        break
                    checked+=1
                    emit('jellyfin',checked=checked,total=total_titles,library=inventory.library)
                    absence[initial.media_key] = result.get('absence_verified') is True
                    signals[initial.media_key] = result['signals'] if result['status'] == 'shape_valid_untrusted' else None
                jf_complete = jf_complete and jf_checked
            except Exception:
                jf_complete = False  # Keep only the fixed status, not the service response or raw error.
            check_deadline()
            emit('arr',checked=checked,total=total_titles,library=inventory.library)
            try:
                prefix, service = ('SONARR','sonarr') if inventory.library == 'TV' else ('RADARR','radarr')
                catalog = catalog_paths_by_folder(arr_factory(service=service,
                    base_url=settings.get(prefix+'_URL',''),token=settings.get(prefix+'_API_KEY','')))
                arr_complete = True
            except Exception:
                arr_complete = False
            check_deadline()
        titles = []
        for title, initial in zip(inventory.titles,preliminary.titles,strict=True):
            matches = catalog.get(title.folder, [])
            status = ('unavailable' if not arr_complete else 'missing_record' if not matches
                else 'ambiguous_record' if len(matches) != 1
                else 'exact_source_match' if matches[0] == roots[inventory.library][title.stage]+'/'+title.folder
                else 'path_conflict')
            titles.append(TitleObservation(initial.media_key,title.stage,title.threshold_days,
                signals.get(initial.media_key),status,
                'tv_season_policy' if is_tv_library(inventory.library, inventory.media_type) and title.folder in season_policy_titles else title.blocker,
                absence.get(initial.media_key,False)))
        observations.append(LibraryObservation(inventory.library,jf_complete,arr_complete,tuple(titles),inventory.media_type))
        collection_status.append({'library':inventory.library,'inventory_complete':inventory.complete,
            'jellyfin_complete':jf_complete,'arr_complete':arr_complete,'titles':len(titles) if inventory.complete else None})
    check_deadline()
    emit('planning',checked=checked,total=total_titles)
    result = plan_scan(snapshot=snapshot,libraries=observations,now=now,
        maximum_titles=maximum_titles,favorites_trigger_keep=favorites == 'true',
        per_library_action_limit=per_library_limit,
        deletion_enabled=settings.get('ALLOW_PERMANENT_DELETE','false') == 'true' and
            settings.get('REMOVAL_DELETION_CONSENT') == 'arr-removal-v1')
    return {**result,'library_status':tuple(collection_status),
        'inventory_independently_verified':False,'freshness_verified':False,
        'season_titles':tuple(sorted(season_titles, key=lambda title: (title.casefold(), title)))}
