"""Bound, scheduled SQLite preview release; no media/Arr/clock write capability.

Binding creation belongs to the approved offline cutover with all auditor writers
stopped. Validation is lock-free/read-only so status remains usable during a
preview. The immutable build profile, frozen effective settings and unchanged
prepared revision-zero state are all mandatory. Environment flags cannot open a
sealed image or enable moves in this release.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_restore import _write_private
from app.sqlite_json import parse_unique_json
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_release_preparation import BACKUP, COMPLETE, REQUEST, _identity, _protected_parent, _read
from app.sqlite_release_recovery import _encode, _local, _prepared_snapshot
from app.sqlite_scheduled_configured_slot import _configured_run_inputs
from app.sqlite_scheduled_paths import _canonical, _open_directory
from app.state_store import GuardedSQLiteStateStore

BINDING = 'preview-release.json'
PROFILE = 'scheduled-preview-v1'


def _revision():
    from app import sqlite_release_profile as build
    if build.PROFILE != PROFILE or not isinstance(build.SOURCE_REVISION, str) or not re.fullmatch('[0-9a-f]{40}', build.SOURCE_REVISION):
        raise RuntimeError('Immutable SQLite preview release profile required')
    return build.SOURCE_REVISION


def _effective(settings):
    from app.config_store import KEYS, DEFAULTS
    values = dict(os.environ if settings is None else settings)
    path = Path(_canonical(values.get('WEB_CONFIG_FILE', '/app/logs/auditor_config.json')))
    parent = _open_directory(str(path.parent))
    try:
        raw, _ = _local(parent, path.name)
    finally:
        os.close(parent)
    saved = parse_unique_json(raw)
    if not isinstance(saved, dict):
        raise RuntimeError('Existing valid saved configuration required')
    _encode(saved)
    values.update({key: str(value) for key, value in saved.items() if key in KEYS})
    for key in KEYS:
        values.setdefault(key, DEFAULTS.get(key, ''))
    for key, default in (('STATE_FILE', '/app/logs/auditor_state.json'),
            ('SQLITE_STATE_FILE', '/app/logs/sqlite_worker/state.db'),
            ('WEB_CONFIG_FILE', '/app/logs/auditor_config.json'), ('READ_ONLY_API_SERVICE', 'false')):
        values.setdefault(key, default)
    return values, hashlib.sha256(raw).hexdigest()


def _policy(values):
    from datetime import datetime
    from app.config_store import KEYS
    if values.get('AUDITOR_STATE_BACKEND') != 'sqlite' or values.get('DRY_RUN', '').strip().lower() != 'true':
        raise RuntimeError('Preview release requires SQLite and DRY_RUN=true')
    if values.get('READ_ONLY_API_SERVICE', 'false').strip().lower() != 'false':
        raise RuntimeError('Combined scheduled preview service required')
    config, _, _ = _configured_run_inputs(settings=values, clock=datetime.now, allow_dry_run=True)
    source = Path(_canonical(values.get('STATE_FILE', '/app/logs/auditor_state.json')))
    database = Path(_canonical(values.get('SQLITE_STATE_FILE', '/app/logs/sqlite_worker/state.db')))
    saved = Path(_canonical(values.get('WEB_CONFIG_FILE', '/app/logs/auditor_config.json')))
    control = database.parent
    if database.name != 'state.db' or source == database or control in source.parents:
        raise RuntimeError('Separate prepared control/state.db required')
    for library in config.libraries:
        for _, root in library.roots:
            media = Path(root)
            if any(media == item or media in item.parents or item in media.parents for item in (source, saved, control)):
                raise RuntimeError('Media, configuration and tracking paths must be disjoint')
    keys = set(KEYS) | {'STATE_FILE', 'SQLITE_STATE_FILE', 'WEB_CONFIG_FILE', 'TZ',
        'AUDITOR_STATE_BACKEND', 'READ_ONLY_API_SERVICE'}
    keys |= {f'{prefix}_{stage}_PATH' for prefix in ('RADARR', 'SONARR')
             for stage in ('TRANSIENT', 'HOLDING', 'KEEP', 'REMOVAL')}
    # Persist only a digest, including credentials/settings without printing them.
    digest = hashlib.sha256(_encode({key: values.get(key, '') for key in sorted(keys)})).hexdigest()
    return config, source, database, digest


def _roots(config, control_identity):
    seen = {tuple(control_identity)}
    result = []
    for library in config.libraries:
        for _, path in library.roots:
            fd = _open_directory(path)
            try:
                info = os.fstat(fd); identity = (info.st_dev, info.st_ino)
                if identity in seen:
                    raise RuntimeError('Aliased preview roots')
                seen.add(identity); result.append([path, *identity])
            finally:
                os.close(fd)
    return result


def create_preview_binding(*, settings=None):
    revision = _revision()
    values, config_sha = _effective(settings)
    config, source, database, policy_sha = _policy(values)
    with _prepared_snapshot(source, database.parent) as (parent, state, state_revision, preparation_id, verify):
        if state_revision != 0:
            raise RuntimeError('Initial unchanged revision-zero preview state required')
        control = os.fstat(parent)
        inputs = {name: hashlib.sha256(_local(parent, name)[0]).hexdigest()
                  for name in (REQUEST, COMPLETE, BACKUP)}
        db = os.stat('state.db', dir_fd=parent, follow_symlinks=False)
        binding = {'schema_version': 1, 'profile': PROFILE, 'source_revision': revision,
            'preparation_id': preparation_id, 'policy_sha256': policy_sha,
            'saved_config_sha256': config_sha, 'prepared_inputs': inputs,
            'control_identity': [control.st_dev, control.st_ino],
            'database_identity': [db.st_dev, db.st_ino], 'snapshot_revision': 0,
            'snapshot_sha256': hashlib.sha256(_encode(state)).hexdigest(),
            'media_roots': _roots(config, (control.st_dev, control.st_ino)),
            'media_actions_authorized': False}
        verify()
        _write_private(parent, BINDING, _encode(binding))
        verify()
        # Re-read the same effective inputs; a changed config never gets a permit.
        latest, latest_sha = _effective(settings)
        if latest_sha != config_sha or _policy(latest)[3] != policy_sha:
            raise RuntimeError('Preview policy changed during binding creation')
        return {'status': 'preview_binding_created', 'execution_mode': 'scheduled_preview',
            'source_revision': revision, 'state_revision': 0, 'media_actions_authorized': False,
            'service_changes_performed': False}


def validate_preview_activation(*, settings=None):
    revision = _revision()
    values, config_sha = _effective(settings)
    config, source, database, policy_sha = _policy(values)
    control = database.parent
    with ExitStack() as stack:
        parent = _open_directory(str(control)); stack.callback(os.close, parent)
        original_control = os.fstat(parent)
        parent_fd = _open_directory(str(control.parent)); stack.callback(os.close, parent_fd)
        info = os.fstat(parent_fd)
        protected_id = (info.st_dev, info.st_ino)
        _protected_parent(control.parent, protected_id)
        if stat.S_IMODE(original_control.st_mode) != 0o700 or original_control.st_uid != os.geteuid():
            raise RuntimeError('Private preview control required')
        captured = {name: _local(parent, name) for name in (BINDING, REQUEST, COMPLETE, BACKUP)}
        binding = parse_unique_json(captured[BINDING][0])
        request = parse_unique_json(captured[REQUEST][0])
        receipt = parse_unique_json(captured[COMPLETE][0])
        if not all(isinstance(item, dict) for item in (binding, request, receipt)):
            raise RuntimeError('Bound preview records required')
        source_parent = _open_directory(str(source.parent)); stack.callback(os.close, source_parent)
        source_parent_info = os.fstat(source_parent)
        source_fd = os.open(source.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source_parent)
        stack.callback(os.close, source_fd)
        original, original_source = _read(source_fd)
        database_fd = os.open('state.db', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        stack.callback(os.close, database_fd)
        db = os.fstat(database_fd)
        if (not stat.S_ISREG(db.st_mode) or db.st_nlink != 1
                or type(binding.get('schema_version')) is not int or binding['schema_version'] != 1
                or binding.get('profile') != PROFILE or binding.get('source_revision') != revision
                or binding.get('policy_sha256') != policy_sha or binding.get('saved_config_sha256') != config_sha
                or binding.get('media_actions_authorized') is not False
                or binding.get('preparation_id') != request.get('request_id')
                or binding.get('control_identity') != [original_control.st_dev, original_control.st_ino]
                or binding.get('database_identity') != [db.st_dev, db.st_ino]
                or receipt.get('database_identity') != [db.st_dev, db.st_ino]
                or binding.get('prepared_inputs') != {name: hashlib.sha256(captured[name][0]).hexdigest()
                    for name in (REQUEST, COMPLETE, BACKUP)}
                or original != captured[BACKUP][0]
                or request.get('source_sha256') != hashlib.sha256(original).hexdigest()
                or request.get('source_identity') != list(_identity(original_source))
                or binding.get('media_roots') != _roots(config, (original_control.st_dev, original_control.st_ino))):
            raise RuntimeError('Preview release binding mismatch')
        session = RevisionedAuditSession(GuardedSQLiteStateStore(Path(f'/proc/self/fd/{parent}') / 'state.db'))
        state, state_revision = session.read_verified_snapshot()
        if (state_revision != 0 or type(binding.get('snapshot_revision')) is not int
                or binding['snapshot_revision'] != 0 or INTENTS_KEY in state
                or binding.get('snapshot_sha256') != hashlib.sha256(_encode(state)).hexdigest()):
            raise RuntimeError('Preview state advanced or changed')
        latest, latest_sha = _effective(settings)
        if latest_sha != config_sha or _policy(latest)[3] != policy_sha:
            raise RuntimeError('Preview configuration changed during validation')
        _protected_parent(control.parent, protected_id)
        source_reopened = _open_directory(str(source.parent)); stack.callback(os.close, source_reopened)
        info = os.fstat(source_reopened)
        if (info.st_dev, info.st_ino) != (source_parent_info.st_dev, source_parent_info.st_ino):
            raise RuntimeError('Preview source parent changed')
        reopened = _open_directory(str(control)); stack.callback(os.close, reopened)
        info = os.fstat(reopened)
        if (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), info.st_uid) != (
                original_control.st_dev, original_control.st_ino, 0o700, os.geteuid()):
            raise RuntimeError('Preview control changed')
        if (_local(source_parent, source.name)[0] != original
                or _identity(os.stat(source.name, dir_fd=source_parent, follow_symlinks=False)) != _identity(original_source)
                or _identity(os.fstat(source_fd)) != _identity(original_source)
                or _identity(os.stat('state.db', dir_fd=parent, follow_symlinks=False)) != _identity(db)
                or _identity(os.fstat(database_fd)) != _identity(db)):
            raise RuntimeError('Preview source or database changed')
        for name, (payload, original_info) in captured.items():
            current, current_info = _local(parent, name)
            if current != payload or _identity(current_info) != _identity(original_info):
                raise RuntimeError('Preview input changed')
        if binding['media_roots'] != _roots(config, (original_control.st_dev, original_control.st_ino)):
            raise RuntimeError('Preview roots changed during validation')
        session.read_verified_snapshot()
        return values


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('action', choices=('bind', 'check'))
    args = parser.parse_args()
    try:
        if args.action == 'bind':
            report = create_preview_binding()
        else:
            validate_preview_activation()
            report = {'status': 'preview_binding_valid', 'execution_mode': 'scheduled_preview',
                'media_actions_authorized': False, 'service_changes_performed': False}
    except Exception as error:
        print(json.dumps({'status': 'preview_release_blocked', 'failure_category': type(error).__name__,
            'media_actions_authorized': False, 'service_changes_performed': False}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
