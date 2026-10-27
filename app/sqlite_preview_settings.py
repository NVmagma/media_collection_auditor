"""Preview settings requests never overwrite the configuration bound to state."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat

from app.config_store import KEYS, DEFAULTS, BOOLS

PENDING = 'auditor_config.pending.json'
MESSAGE = ('Requested settings saved. Your active settings have not changed. '
           'The request needs to be validated and applied before it takes effect.')


def request_settings(*, config_path, updated, environment=None):
    environment = dict(os.environ if environment is None else environment)
    path = Path(config_path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 2*1024*1024:
            raise ValueError('Active settings need review; no changes were saved.')
        raw = stream.read(2*1024*1024+1)
    from app.sqlite_json import parse_unique_json
    try:
        current = parse_unique_json(raw)
    except Exception:
        raise ValueError('Active settings need review; no changes were saved.') from None
    if not isinstance(current, dict): raise ValueError('Active settings need review; no changes were saved.')
    proposed = {key:value for key,value in current.items() if key not in KEYS}
    proposed.update({key:value for key,value in updated.items() if key in KEYS})
    def effective(values):
        result = {key:str(values.get(key, environment.get(key, DEFAULTS.get(key,'')))) for key in KEYS}
        return {key:value.lower() if key in BOOLS else value for key,value in result.items()}
    before, after = effective(current), effective(proposed)
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
