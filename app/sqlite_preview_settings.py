"""Preview settings requests never overwrite the configuration bound to state."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat

from app.config_store import KEYS, DEFAULTS, BOOLS

PENDING = 'auditor_config.pending.json'
def _read_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 2*1024*1024:
            raise ValueError('Settings file needs review.')
        raw = stream.read(2*1024*1024+1)
    if len(raw) > 2*1024*1024:
        raise ValueError('Settings file needs review.')
    return raw


def _effective(values, environment):
    result = {key:str(values.get(key, environment.get(key, DEFAULTS.get(key,'')))) for key in KEYS}
    return {key:value.lower() if key in BOOLS else value for key,value in result.items()}


def pending_request_summary(*, config_path, environment=None):
    """Detached status and allowlisted key names only; never return setting values."""
    from app.sqlite_json import parse_unique_json
    path = Path(config_path)
    environment = dict(os.environ if environment is None else environment)
    try:
        pending_raw = _read_regular(path.parent / PENDING)
    except FileNotFoundError:
        return {'status':'none', 'changed_keys':[]}
    except (OSError, ValueError):
        return {'status':'review_required', 'changed_keys':[]}
    try:
        raw = _read_regular(path)
        current = parse_unique_json(raw)
        pending = parse_unique_json(pending_raw)
        if (not isinstance(current,dict) or not isinstance(pending,dict)
                or pending.get('schema_version') != 1
                or pending.get('media_actions_authorized') is not False
                or not isinstance(pending.get('requested_config'),dict)):
            raise ValueError('Settings request needs review')
        if pending.get('base_config_sha256') != hashlib.sha256(raw).hexdigest():
            return {'status':'stale', 'changed_keys':[]}
        before = _effective(current,environment)
        after = _effective(pending['requested_config'],environment)
        return {'status':'requested', 'changed_keys':sorted(key for key in KEYS if before[key] != after[key])}
    except Exception:
        return {'status':'review_required', 'changed_keys':[]}


def request_settings(*, config_path, updated, environment=None):
    environment = dict(os.environ if environment is None else environment)
    path = Path(config_path)
    try:
        raw = _read_regular(path)
    except (OSError, ValueError):
        raise ValueError('Active settings need review; no changes were saved.') from None
    from app.sqlite_json import parse_unique_json
    try:
        current = parse_unique_json(raw)
    except Exception:
        raise ValueError('Active settings need review; no changes were saved.') from None
    if not isinstance(current, dict): raise ValueError('Active settings need review; no changes were saved.')
    proposed = {key:value for key,value in current.items() if key not in KEYS}
    proposed.update({key:value for key,value in updated.items() if key in KEYS})
    before, after = _effective(current, environment), _effective(proposed, environment)
    if (after['DRY_RUN'].lower() != 'true' or any(after[key].lower() != 'false' for key in (
            'ALLOW_FILESYSTEM_DELETE','ALLOW_PERMANENT_DELETE','ALLOW_CROSS_FILESYSTEM_MOVES','ENABLE_SEASON_PRUNING'))):
        raise ValueError('This preview cannot enable media actions or season pruning. Active settings were not changed.')
    changed = sorted(key for key in KEYS if before[key] != after[key])
    if not changed: return {'status':'unchanged','active_settings_changed':False}
    payload = {'schema_version':1, 'base_config_sha256':hashlib.sha256(raw).hexdigest(),
               'requested_config':proposed, 'media_actions_authorized':False}
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = '.pending-settings-'+secrets.token_hex(12)
    try:
        # New private file + atomic replacement; no active file is written.
        out = os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
        with os.fdopen(out,'wb') as stream:
            stream.write(json.dumps(payload,sort_keys=True,allow_nan=False).encode()+b'\n'); stream.flush(); os.fsync(stream.fileno())
        if path.read_bytes() != raw:
            raise ValueError('Active settings changed during the request. Please reload and try again.')
        os.replace(temporary,PENDING,src_dir_fd=parent,dst_dir_fd=parent); os.fsync(parent)
    finally:
        try: os.unlink(temporary,dir_fd=parent)
        except FileNotFoundError: pass
        os.close(parent)
    return {'status':'requested','active_settings_changed':False}
