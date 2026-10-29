"""Reviewed live settings use the shared journal without changing tracking or caps."""
from types import SimpleNamespace
import os
from app.config_store import KEYS,DEFAULTS
from app.sqlite_live_policy import validate_initial_live_policy
from app.sqlite_live_binding import (BINDING,_revision,_policy,_media,
    validate_live_binding,_validate_bound_live)
from app.sqlite_preview_settings import request_settings as stage_request
from app.sqlite_preview_settings_apply import apply_requested_settings as shared_apply
from app.sqlite_preview_settings_apply import restore_previous_settings as shared_restore

LOCKED = frozenset(('DRY_RUN','MAX_ACTIONS_PER_RUN','MEDIA_PATH','SQLITE_DAILY_RUN_TIMEZONE',
    'ALLOW_PERMANENT_DELETE','ALLOW_FILESYSTEM_DELETE','ALLOW_CROSS_FILESYSTEM_MOVES','ENABLE_SEASON_PRUNING'))


def _values(saved,environment):
    result=dict(environment)
    for key in KEYS:result.setdefault(key,DEFAULTS.get(key,''))
    result.update({key:value for key,value in saved.items() if key in KEYS})
    return result


def _validate_change(before,after):
    validate_initial_live_policy(after)
    if any(before.get(key,'')!=after.get(key,'') for key in LOCKED):
        raise ValueError('Canary safety controls, media root and time zone remain fixed.')


def _validate_values(values,settings,previous):
    _validate_change(_values(previous,settings),values)


def _check_revision(value):
    if type(value) is not int or value<0:raise RuntimeError('Valid live revision required')


def _protocol():
    return SimpleNamespace(binding=BINDING,revision=_revision,policy=_policy,roots=_media,
        validate=lambda **kwargs:validate_live_binding(**kwargs,for_execution=True),
        validate_bound=lambda **kwargs:_validate_bound_live(**kwargs,for_execution=True,allow_settings_marker=True),
        check_revision=_check_revision,validate_values=_validate_values)


def request_settings(*,config_path,updated,environment=None,include_digest=False):
    environment=dict(os.environ if environment is None else environment)
    try:validate_live_binding(settings=environment,for_execution=True)
    except Exception:raise ValueError('Active live settings need review; no changes were saved.') from None
    return stage_request(config_path=config_path,updated=updated,environment=environment,
        include_digest=include_digest,_validate_change=lambda before,after:_validate_change(
            {**environment,**before},{**environment,**after}))


def apply_requested_settings(*,settings,request_sha256):
    return shared_apply(settings=settings,request_sha256=request_sha256,_protocol=_protocol())


def restore_previous_settings(*,settings,request_sha256):
    return shared_restore(settings=settings,request_sha256=request_sha256,_protocol=_protocol())
