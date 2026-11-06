"""Read-only season preview for one explicitly selected TV show."""
from datetime import datetime
import os
from pathlib import Path
import re
import stat

from app.arr_catalog import ArrCatalogGET, catalog_paths_by_folder
from app.filesystem_paths import _open_directory, scan_held_directory
from app.jellyfin_collection import collect_title_observation
from app.jellyfin_transport import ScheduledJellyfinGET
from app.json_worker_cycle import stage_paths
from app.orphan_inventory import VIDEO_SUFFIXES, inspect_title
from app.title_identity import validate_title_folder
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
    show = Path(roots[stage]) / title
    fd = _open_directory(str(show))
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (device, inode):
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
                match = re.fullmatch(r'Season ([0-9]{1,4})', entry.name, re.IGNORECASE)
                if not match or int(match[1]) in seasons:
                    raise RuntimeError('Season folders could not be identified uniquely')
                seasons[int(match[1])] = inspect_title(str(show / entry.name))
        if os.fstat(fd).st_ctime_ns != opened.st_ctime_ns:
            raise RuntimeError('Show changed during review')
        if any(item['status'] == 'unknown_files' for item in seasons.values()):
            raise RuntimeError('Season contains unclassified files')
        return stage, (device, inode), seasons
    finally:
        os.close(fd)


def review_show(title, settings):
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
    stage, _, seasons = inventory
    expected_path = remote[stage] + '/' + title
    sonarr = ArrCatalogGET(service='sonarr', base_url=captured.get('SONARR_URL', ''),
                           token=captured.get('SONARR_API_KEY', ''))
    if catalog_paths_by_folder(sonarr).get(title) != [expected_path]:
        raise RuntimeError('Sonarr show path could not be verified')
    jellyfin = ScheduledJellyfinGET(base_url=captured.get('JELLYFIN_HOST_URL', ''),
                                  token=captured.get('JELLYFIN_API_TOKEN', ''), maximum_requests=200)
    result = collect_title_observation(fetch=jellyfin, jellyfin_type='Series', folder=title,
                                       media_key='TV/' + title, now=datetime.now())
    if (result['status'] != 'shape_valid_untrusted'
            or result['identity'][1] not in (expected_path, local[stage] + '/' + title)):
        raise RuntimeError('Jellyfin show or tag coverage could not be verified')
    if settings() != captured or _inventory(local, title) != inventory:
        raise RuntimeError('Season review inputs changed')
    tags = set(result['observed_tags'])
    if captured.get('PROTECT_TAG', 'keep-forever').casefold() in tags:
        tags.add('keep-forever')
    return plan_seasons(tags=tags,
                        active=[number for number, item in seasons.items() if item['status'] == 'video_present'],
                        leaving_soon=[], verified=True,
                        keep_all_tag=captured.get('KEEP_ALL_SEASONS_TAG', 'keep-all-seasons'))
