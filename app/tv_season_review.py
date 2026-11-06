"""Read-only season preview for one explicitly selected TV show."""
from datetime import datetime
import os
from pathlib import Path
import stat

from app.arr_catalog import ArrCatalogGET, canonical_arr_record_path, catalog_paths_by_folder
from app.filesystem_paths import _canonical, _open_directory, scan_held_directory
from app.jellyfin_collection import collect_title_observation
from app.jellyfin_transport import ScheduledJellyfinGET
from app.json_worker_cycle import stage_paths
from app.orphan_inventory import VIDEO_SUFFIXES, inspect_title
from app.title_identity import validate_title_folder
from app.tv_season_move import ARCHIVE, SEASON_FOLDER
from app.tv_season_policy import plan_seasons


def _inventory(roots, title):
    locations = []
    for stage, root in roots.items():
        fd = _open_directory(root)
        try:
            try:
                item = os.stat(title, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(item.st_mode):
                raise RuntimeError('Show path is not a directory')
            locations.append((stage, item.st_dev, item.st_ino))
        finally:
            os.close(fd)
    if len(locations) != 1 or locations[0][0] not in ('Waiting', 'Keep'):
        raise RuntimeError('An exact, active show folder is required')
    stage, device, inode = locations[0]
    return stage, _show_seasons(Path(roots[stage]) / title, expected=(device, inode))


def _show_seasons(show, *, expected=None):
    fd = _open_directory(str(show))
    try:
        opened = os.fstat(fd)
        identity = (opened.st_dev, opened.st_ino)
        if expected is not None and identity != expected:
            raise RuntimeError('Show folder changed')
        seasons = {}
        with scan_held_directory(fd) as entries:
            for index, entry in enumerate(entries, 1):
                if index > 1000:
                    raise RuntimeError('Show inventory limit exceeded')
                if entry.is_symlink():
                    raise RuntimeError('Show contains a symlink')
                if not entry.is_dir(follow_symlinks=False):
                    if Path(entry.name).suffix.lower() in VIDEO_SUFFIXES:
                        raise RuntimeError('Show has loose video files')
                    continue
                if entry.name.casefold() == 'specials':
                    continue
                match = SEASON_FOLDER.fullmatch(entry.name)
                if not match or int(match[1]) in seasons:
                    raise RuntimeError('Season folders could not be identified uniquely')
                seasons[int(match[1])] = {'name': entry.name, **inspect_title(str(show / entry.name))}
        if os.fstat(fd).st_ctime_ns != opened.st_ctime_ns:
            raise RuntimeError('Show changed during review')
        if any(item['status'] == 'unknown_files' for item in seasons.values()):
            raise RuntimeError('Season contains unclassified files')
        return identity, seasons
    finally:
        os.close(fd)



def season_holding_root(settings):
    base = _canonical(settings.get('MEDIA_PATH', '/media'))
    holding = Path(_canonical(settings.get('TV_SEASON_HOLDING_PATH') or base + '/TV_seasons_leaving_soon'))
    for library in ('TV', 'Movies'):
        for value in stage_paths(settings, library)[0].values():
            root = Path(value)
            if root == holding or root in holding.parents or holding in root.parents:
                raise ValueError('Season Holding must be separate from whole-title stages')
    return holding


def _staged_inventory(holding, title, active, state):
    archive = state.get(ARCHIVE, {})
    if not isinstance(archive, dict):
        raise RuntimeError('Season tracking unavailable')
    prefix = f'TV/{title}/'
    records = {key[len(prefix):]: item for key, item in archive.items() if key.startswith(prefix)}
    show = holding / title
    try:
        identity, seasons = _show_seasons(show)
    except FileNotFoundError:
        if not records:
            return None, {}
        raise RuntimeError('Tracked staged seasons are missing') from None
    if set(records) != {str(number) for number in seasons}:
        raise RuntimeError('Untracked or missing staged seasons')
    for number, season in seasons.items():
        record = records[str(number)]
        if (not isinstance(record, dict) or number < 1 or season['status'] != 'video_present'
                or record.get('name') != season['name'] or record.get('identity') != season['identity']
                or record.get('active_parent') != str(active) or record.get('holding_parent') != str(show)):
            raise RuntimeError('Tracked staged season identity changed')
    return identity, seasons

def inspect_show(title, settings, load_state):
    validate_title_folder(title)
    if title.startswith('.') or len(title) > 255:
        raise ValueError('Invalid TV show folder')
    captured = settings()
    if captured.get('ENABLE_TV') != 'true':
        raise RuntimeError('TV scanning disabled')
    local, remote = stage_paths(captured, 'TV')
    if len(set(local.values())) != 4 or len(set(remote.values())) != 4:
        raise RuntimeError('Distinct TV stage paths required')
    inventory = _inventory(local, title)
    stage, (_, seasons) = inventory
    state = load_state()
    holding = season_holding_root(captured)
    active = Path(local[stage]) / title
    staged_inventory = _staged_inventory(holding, title, active, state)
    staged = staged_inventory[1]
    if seasons.keys() & staged.keys():
        raise RuntimeError('Season is present in both active and Holding folders')
    expected_path = remote[stage] + '/' + title
    sonarr = ArrCatalogGET(service='sonarr', base_url=captured.get('SONARR_URL', ''),
                           token=captured.get('SONARR_API_KEY', ''))
    catalog = sonarr()
    if catalog_paths_by_folder(lambda: catalog).get(title) != [expected_path]:
        raise RuntimeError('Sonarr show path could not be verified')
    series_id = next(row['id'] for row in catalog if canonical_arr_record_path(row['path']) == expected_path)
    jellyfin = ScheduledJellyfinGET(base_url=captured.get('JELLYFIN_HOST_URL', ''),
                                  token=captured.get('JELLYFIN_API_TOKEN', ''), maximum_requests=200)
    tag_names = {name: captured.get(key, default) for name, key, default in (
        ('keep', 'KEEP_TAG', 'keep'), ('disliked', 'DISLIKE_TAG', 'not-at-all'),
        ('keep_all', 'KEEP_ALL_SEASONS_TAG', 'keep-all-seasons'),
        ('protected', 'PROTECT_TAG', 'keep-forever'))}
    result = collect_title_observation(fetch=jellyfin, jellyfin_type='Series', folder=title,
                                       media_key='TV/' + title, now=datetime.now(), tag_names=tag_names,
                                       excluded_series_path=str(holding / title) if staged else None)
    if (result['status'] != 'shape_valid_untrusted'
            or result['identity'][1] not in (expected_path, local[stage] + '/' + title)):
        raise RuntimeError('Jellyfin show or tag coverage could not be verified')
    if (settings() != captured or load_state().get(ARCHIVE, {}) != state.get(ARCHIVE, {})
            or _inventory(local, title) != inventory
            or _staged_inventory(holding, title, active, state) != staged_inventory):
        raise RuntimeError('Season review inputs changed')
    tags = set(result['observed_tags'])
    if captured.get('PROTECT_TAG', 'keep-forever').casefold() in tags:
        tags.add('keep-forever')
    plan = plan_seasons(tags=tags,
                        active=[number for number, item in seasons.items() if item['status'] == 'video_present'],
                        leaving_soon=staged.keys(), verified=True,
                        keep_all_tag=captured.get('KEEP_ALL_SEASONS_TAG', 'keep-all-seasons'))

    return {'plan': plan, 'active_parent': active, 'holding_parent': holding / title,
            'active': seasons, 'staged': staged, 'series_id': series_id, 'sonarr_path': expected_path,
            'tags': tags, 'signals': result['signals']}


def review_show(title, settings, load_state):
    return inspect_show(title, settings, load_state)['plan']
