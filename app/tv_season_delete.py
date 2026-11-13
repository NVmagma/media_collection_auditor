"""Save an intent, isolate the season, then delete only the verified expired files."""
from contextlib import ExitStack
from datetime import datetime, timedelta
import os
from pathlib import Path
import secrets
import shutil
import stat

from app.arr_import_service import media_fingerprint
from app.atomic_rename import rename_directory_noreplace_at
from app.deletion_policy import protected
from app.filesystem_paths import _open_directory
from app.mount_identity import assert_rename_mount_binding, capture_rename_mount_binding, read_fd_mount_id
from app.tv_season_deletion_policy import validate_season_deletion
from app.tv_season_move import _identity, verify_season_location
from app.tv_season_policy import ARCHIVE


def expired_season(record, *, now, days):
    try:
        stamp = datetime.fromisoformat(record['staged_at'])
        return (stamp.tzinfo is not None and stamp + timedelta(days=days) <= now
                and bool(record.get('media_fingerprint')) and type(record.get('media_files')) is int)
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


def eligible_for_deletion(review, season):
    plan = review['plan']
    return ('one-season' in review['tags'] and not protected(review['signals'])
            and not plan.blocked and not plan.restore and plan.latest in review['active']
            and season in review['staged'] and 0 < season < plan.latest)


def _tree(fd):
    mount = read_fd_mount_id(fd)
    rows = []
    for base, dirs, files, directory in os.fwalk('.', dir_fd=fd, follow_symlinks=False):
        if len(Path(base).parts) > 16 or read_fd_mount_id(directory) != mount:
            raise RuntimeError('Season deletion cannot cross a nested mount')
        for name in dirs + files:
            item = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if len(rows) >= 20000 or not (stat.S_ISREG(item.st_mode) or stat.S_ISDIR(item.st_mode)):
                raise RuntimeError('Unsupported or excessive season contents')
            rows.append((base, name, item.st_mode, item.st_dev, item.st_ino,
                         item.st_size, item.st_mtime_ns, item.st_ctime_ns))
    return sorted(rows)


def delete_season(attempt, *, title, season, review, now, read_review, monitoring, read_settings, check_playback=None):
    """Journal and isolate one confirmed season; never replay an interrupted delete."""
    session = attempt.session
    attempt._active()
    key = f'TV/{title}/{season}'
    record = session.state.get(ARCHIVE, {}).get(key)
    settings = read_settings()
    if (settings.get('DRY_RUN', 'true') != 'false' or not validate_season_deletion(settings)
            or record is None or not expired_season(record, now=now, days=int(settings.get('HOLDING_DAYS', '7')))
            or not eligible_for_deletion(review, season)):
        raise RuntimeError('Season deletion is not eligible')
    holding = review['holding_parent']
    name = review['staged'][season]['name']
    if (record['holding_parent'] != str(holding) or record['name'] != name
            or record['sonarr_endpoint'] != monitoring.endpoint_identity
            or record['sonarr_series_id'] != monitoring.series_id
            or record['sonarr_path'] != monitoring.source_path or monitoring.season != season):
        raise RuntimeError('Season deletion binding changed')

    with ExitStack() as stack:
        parent = _open_directory(str(holding))
        stack.callback(os.close, parent)
        witness = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        stack.callback(os.close, witness)
        if _identity(os.fstat(witness)) != record['identity']:
            raise RuntimeError('Staged season replaced')
        tree = _tree(witness)
        fingerprint = record['media_fingerprint'], record['media_files']
        if media_fingerprint(witness) != fingerprint or not shutil.rmtree.avoids_symlink_attacks:
            raise RuntimeError('Staged media changed or safe deletion is unavailable')
        if monitoring.read() is not False or monitoring.read() is not False:
            raise RuntimeError('Sonarr monitoring changed')
        if read_review() != review or read_settings() != settings:
            raise RuntimeError('Season deletion review changed')
        if check_playback is not None:
            check_playback(title, str(holding / name), season)
        session.verify()
        if _tree(witness) != tree:
            raise RuntimeError('Season contents changed')

        # Use a private, unique directory beside the staged season. An interrupted
        # delete remains journaled and its contents are never automatically purged.
        isolated = '.season-delete-' + secrets.token_hex(16)
        os.mkdir(isolated, 0o700, dir_fd=parent)
        private = os.open(isolated, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        stack.callback(os.close, private)
        binding = capture_rename_mount_binding(parent, private, witness)
        verify_season_location(parent, private, name, season, record['identity'])
        if _identity(os.fstat(parent)) != _identity(holding.stat(follow_symlinks=False)):
            raise RuntimeError('Staged show folder changed')
        os.fsync(parent)
        identifier = attempt.record_intent(kind='tv_season_delete', library='TV', title=title,
            details={'key': key, 'record': record, 'isolation_folder': isolated})
        if read_settings() != settings or _tree(witness) != tree:
            raise RuntimeError('Season deletion authorization or contents changed')
        rename_directory_noreplace_at(parent, name, private, name)
        os.fsync(parent)
        os.fsync(private)
        verify_season_location(private, parent, name, season, record['identity'])
        if (read_settings() != settings or _tree(witness) != tree
                or _identity(os.stat(isolated, dir_fd=parent, follow_symlinks=False)) != _identity(os.fstat(private))):
            raise RuntimeError('Isolated season changed')
        assert_rename_mount_binding(binding, parent, private, witness)
        shutil.rmtree(name, dir_fd=private)
        os.fsync(private)
        os.rmdir(isolated, dir_fd=parent)
        os.fsync(parent)
        del session.state[ARCHIVE][key]
        attempt.finish_operation(identifier=identifier, verify_outcome=lambda _: True)
