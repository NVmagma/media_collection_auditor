"""Read-only release observations; run via docker exec python -B - < this file.

Standard library only; no application imports, writes, locks, service calls or
credential/title output. This is not a stopped-writer or activation permit.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import stat
from zoneinfo import ZoneInfo

FLAGS = {'DRY_RUN': 'true', 'ALLOW_PERMANENT_DELETE': 'false',
    'ALLOW_FILESYSTEM_DELETE': 'false', 'ALLOW_CROSS_FILESYSTEM_MOVES': 'false',
    'ENABLE_SEASON_PRUNING': 'false', 'ENABLE_MOVIES': 'true', 'ENABLE_TV': 'false',
    'FAVORITES_TRIGGER_KEEP': 'true', 'TV_NEW_EPISODES_RESET_CLOCK': 'true'}
NUMBERS = {'MAX_ACTIONS_PER_RUN': '10', 'MOVIE_WAIT_DAYS': '30', 'TV_WAIT_DAYS': '60',
           'HOLDING_DAYS': '7', 'REMOVAL_DAYS': '7'}
SAVED_KEYS = set(FLAGS) | set(NUMBERS) | {'MEDIA_PATH', 'SQLITE_DAILY_RUN_TIME', 'SQLITE_DAILY_RUN_TIMEZONE'}
SECTIONS = ('first_seen', 'queued', 'keep_seen', 'in_removal', 'arr_sync_pending')
MAXIMUM = 64 * 1024 * 1024


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate key')
        result[key] = value
    return result


def canonical(path):
    return (isinstance(path, str) and path.startswith('/') and path != '/'
        and str(PurePosixPath(path)) == path and '..' not in PurePosixPath(path).parts
        and not path.startswith('//') and '\\' not in path
        and not any(ord(c) < 32 or ord(c) == 127 for c in path))


def open_directory(path):
    if not canonical(path): raise ValueError('Canonical path required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in PurePosixPath(path).parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            os.close(fd); fd = child
        return fd
    except BaseException:
        os.close(fd); raise


def read_private_json(path):
    if not canonical(path): raise ValueError('Canonical file path required')
    parent = open_directory(str(PurePosixPath(path).parent))
    try:
        fd = os.open(PurePosixPath(path).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAXIMUM:
                raise ValueError('Regular bounded file required')
            chunks = bytearray()
            while len(chunks) <= MAXIMUM:
                chunk = os.read(fd, min(65536, MAXIMUM + 1 - len(chunks)))
                if not chunk: break
                chunks.extend(chunk)
            def identity(info):
                return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)
            current = os.stat(PurePosixPath(path).name, dir_fd=parent, follow_symlinks=False)
            if len(chunks) > MAXIMUM or identity(before) != identity(os.fstat(fd)) or identity(before) != identity(current):
                raise ValueError('File changed')
            def invalid(value): raise ValueError('Nonfinite value')
            data = json.loads(chunks, object_pairs_hook=unique, parse_constant=invalid)
            if not isinstance(data, dict): raise ValueError('Object required')
            return data, {'sha256': hashlib.sha256(chunks).hexdigest(), 'bytes': len(chunks),
                'device': before.st_dev, 'inode': before.st_ino, 'mode': oct(before.st_mode & 0o777),
                'uid': before.st_uid, 'gid': before.st_gid}
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def directory_observation(path):
    if not canonical(path): return {'status': 'invalid_path'}
    try:
        fd = open_directory(path)
        try:
            info = os.fstat(fd)
            return {'status': 'observed', 'path': path, 'device': info.st_dev, 'inode': info.st_ino,
                    'mode': oct(info.st_mode & 0o777), 'uid': info.st_uid, 'gid': info.st_gid}
        finally:
            os.close(fd)
    except (OSError, ValueError):
        return {'status': 'unavailable_or_aliased', 'path': path}


def report(environment):
    env = dict(environment)
    values = dict(env)
    config_path = env.get('WEB_CONFIG_FILE', '/app/logs/auditor_config.json')
    try:
        saved, _ = read_private_json(config_path)
        values.update({key: str(value) for key, value in saved.items() if key in SAVED_KEYS})
        config_status = 'observed'
    except (OSError, ValueError, TypeError, UnicodeError):
        config_status = 'unavailable_or_invalid'
    settings = {}
    for key, default in FLAGS.items():
        value = str(values.get(key, default)).strip().lower()
        settings[key] = value if value in ('true', 'false') else 'invalid'
    for key, default in NUMBERS.items():
        value = str(values.get(key, default)).strip()
        settings[key] = value if value.isascii() and value.isdecimal() and len(value) <= 6 and int(value) <= 100000 else 'invalid'
    time = values.get('SQLITE_DAILY_RUN_TIME', '')
    settings['SQLITE_DAILY_RUN_TIME'] = time if isinstance(time, str) and (time == '' or re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', time)) else 'invalid'
    zone = values.get('SQLITE_DAILY_RUN_TIMEZONE', '')
    try:
        if not isinstance(zone, str) or len(zone) > 128:
            raise ValueError('Invalid zone')
        if zone: ZoneInfo(zone)
        settings['SQLITE_DAILY_RUN_TIMEZONE'] = zone
    except (ValueError, TypeError, KeyError):
        settings['SQLITE_DAILY_RUN_TIMEZONE'] = 'invalid'
    backend = env.get('AUDITOR_STATE_BACKEND', 'json')
    settings['AUDITOR_STATE_BACKEND'] = backend if backend in ('json', 'sqlite') else 'invalid'
    source = env.get('STATE_FILE', '/app/logs/auditor_state.json')
    source_report = {'status': 'unavailable_or_invalid', 'snapshot_validated': False}
    try:
        state, identity = read_private_json(source)
        if not all(isinstance(state.get(section), dict) for section in SECTIONS):
            raise ValueError('Missing state sections')
        source_report.update(status='shape_observed', path=source, **identity,
            counts={section: len(state[section]) for section in SECTIONS},
            pending_operation_present='sqlite_pending_operations' in state)
    except (OSError, ValueError, TypeError, UnicodeError):
        pass
    database = env.get('SQLITE_STATE_FILE', '/app/logs/sqlite_worker/state.db')
    libraries = {}
    media = values.get('MEDIA_PATH', '/media')
    for name, prefix, enabled, folder in (('Movies', 'RADARR', 'ENABLE_MOVIES', 'Movies'),
                                         ('TV', 'SONARR', 'ENABLE_TV', 'TV')):
        if settings[enabled] != 'true': continue
        if not canonical(media):
            libraries[name] = {'status': 'invalid_media_base'}
            continue
        libraries[name] = {stage: directory_observation(env.get(prefix + '_' + stage.upper() + '_PATH')
            or str(PurePosixPath(media) / (folder + suffix))) for stage, suffix in
            (('transient', ''), ('holding', '_hold'), ('keep', '_keep'), ('removal', '_removal'))}
    return {'status': 'release_review_required', 'read_only': True,
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'probe_identity': {'uid': os.getuid(), 'gid': os.getgid()}, 'saved_config_status': config_status,
        'prospective_effective_settings': settings, 'source_json': source_report,
        'sqlite_control_directory': directory_observation(str(PurePosixPath(database).parent)) if canonical(database) else {'status': 'invalid_path'},
        'libraries': libraries, 'writer_quiescence_verified': False, 'source_snapshot_validated': False,
        'production_activation': 'disabled', 'production_authorized': False}


if __name__ == '__main__':
    print(json.dumps(report(os.environ), sort_keys=True, indent=2))
