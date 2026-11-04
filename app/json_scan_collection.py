"""GET-only service adapters for the isolated JSON advisory planner.

Inventory is supplied by a trusted local adapter; this module does not verify
filesystem inventory or grant move permission. No claims or state saves.
"""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath
from time import monotonic
import math

from app.json_lifecycle_plan import LibraryObservation, TitleObservation, plan_scan
from app.arr_catalog import ArrCatalogGET, canonical_arr_record_path
from app.jellyfin_collection import collect_title_observation, validated_tag_names
from app.jellyfin_scan_cache import _ScanCatalog
from app.filesystem_paths import _canonical
from app.jellyfin_transport import ScheduledJellyfinGET


@dataclass(frozen=True)
class InventoryTitle:
    folder: str
    stage: str
    threshold_days: int
    blocker: str | None = None


@dataclass(frozen=True)
class LibraryInventory:
    library: str
    roots: tuple  # Explicit Arr-visible stage paths, with configured aliases applied.
    titles: tuple
    complete: bool


def _catalog(fetch):
    rows = fetch()
    if not isinstance(rows, list) or len(rows) > 100000: raise ValueError('Invalid Arr catalog')
    folders, ids = {}, set()
    for row in rows:
        if (not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] <= 0
                or row['id'] in ids or type(row.get('monitored')) is not bool):
            raise ValueError('Invalid Arr identity')
        path = canonical_arr_record_path(row.get('path'))
        ids.add(row['id'])
        folders.setdefault(PurePosixPath(path).name, []).append(path)
    return folders


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
    # Validate identities and snapshot before any remote request.
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
            key = ('TV/' if inventory.library == 'TV' else '') + title.folder
            titles.append(TitleObservation(key,title.stage,title.threshold_days,None,'unavailable',title.blocker))
        prelim.append(LibraryObservation(inventory.library,False,False,tuple(titles)))
    plan_scan(snapshot=snapshot,libraries=prelim,now=now,maximum_titles=maximum_titles)
    tags = validated_tag_names({name:settings.get(key, default) for name,key,default in (
        ('keep','KEEP_TAG','keep'), ('disliked','DISLIKE_TAG','not-at-all'),
        ('keep_all','KEEP_ALL_SEASONS_TAG','keep-all-seasons'), ('protected','PROTECT_TAG','keep-forever'))})
    favorites = settings.get('FAVORITES_TRIGGER_KEEP','true')
    if isinstance(favorites,str): favorites = favorites.strip().lower()
    if favorites not in ('true','false'): raise ValueError('Explicit favorites policy required')
    observations, collection_status = [], []
    for inventory, preliminary in zip(inventories,prelim,strict=True):
        check_deadline()
        jf_complete = arr_complete = False
        signals = {}
        catalog = {}
        if inventory.complete and inventory.titles:
            try:
                fetch = jellyfin_factory(base_url=settings.get('JELLYFIN_HOST_URL',''),
                    token=settings.get('JELLYFIN_API_TOKEN',''))
                cached = _ScanCatalog(fetch)
                jf_complete = True
                jf_checked = False
                for title, initial in zip(inventory.titles,preliminary.titles,strict=True):
                    check_deadline()
                    if title.blocker is not None:
                        continue
                    jf_checked = True
                    result = collect_title_observation(fetch=cached,
                        jellyfin_type='Series' if inventory.library == 'TV' else 'Movie',
                        folder=title.folder,media_key=initial.media_key,now=now,tag_names=tags)
                    if 'jellyfin_collection_incomplete' in result['blockers']:
                        jf_complete = False
                        break
                    signals[initial.media_key] = result['signals'] if result['status'] == 'shape_valid_untrusted' else None
                jf_complete = jf_complete and jf_checked
            except Exception:
                jf_complete = False  # Fixed status only; no remote exception/payload retained.
            check_deadline()
            try:
                prefix, service = ('SONARR','sonarr') if inventory.library == 'TV' else ('RADARR','radarr')
                catalog = _catalog(arr_factory(service=service,
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
                signals.get(initial.media_key),status,title.blocker))
        observations.append(LibraryObservation(inventory.library,jf_complete,arr_complete,tuple(titles)))
        collection_status.append({'library':inventory.library,'inventory_complete':inventory.complete,
            'jellyfin_complete':jf_complete,'arr_complete':arr_complete,'titles':len(titles) if inventory.complete else None})
    check_deadline()
    result = plan_scan(snapshot=snapshot,libraries=observations,now=now,
        maximum_titles=maximum_titles,favorites_trigger_keep=favorites == 'true',
        per_library_action_limit=per_library_limit,
        deletion_enabled=settings.get('ALLOW_PERMANENT_DELETE','false') == 'true' and
            settings.get('REMOVAL_DELETION_CONSENT') == 'arr-removal-v1')
    return {**result,'library_status':tuple(collection_status),
        'inventory_independently_verified':False,'freshness_verified':False}
