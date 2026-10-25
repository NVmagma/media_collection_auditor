"""Offline preview preparation and settings recovery; never control services.

The caller must stop all auditor writers first. These operations retain durable
requests on interruption, never overwrite JSON tracking, and never resume a
container. Production invocation belongs to the final approved cutover package.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import secrets
import re
import stat

from app.sqlite_disposable_restore import _write_private
from app.sqlite_json import parse_unique_json
from app.sqlite_preview_activation import create_preview_binding, validate_preview_activation, _revision, _policy, _roots
from app.sqlite_release_preparation import prepare_release_state, _protected_parent, _identity
from app.sqlite_release_recovery import _encode, _local, _prepared_snapshot
from app.sqlite_scheduled_paths import _canonical, _open_directory

REQUEST = 'preview-install-request.json'
COMPLETE = 'preview-install-complete.json'
CONFIG_BACKUP = 'original-config.json'
CONFIG_PROPOSED = 'preview-config.json'
ROLLBACK_REQUEST = 'preview-rollback-request.json'
ROLLBACK_COMPLETE = 'preview-rollback-complete.json'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _boundary(phase):
    """Test fault boundary. No external controls or retry behavior."""


def _private_root(path, expected):
    fd = _open_directory(str(path))
    try:
        info = os.fstat(fd)
        if ((info.st_dev, info.st_ino) != expected or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise RuntimeError('Private install control binding mismatch')
        _protected_parent(path, expected)
        return fd
    except BaseException:
        os.close(fd); raise


def _replace_config(parent, name, expected_raw, expected_info, proposed):
    current, info = _local(parent, name)
    if current != expected_raw or _identity(info) != _identity(expected_info):
        raise RuntimeError('Saved settings changed before replacement')
    staging = '.sqlite-preview-config-' + secrets.token_hex(16)
    _write_private(parent, staging, proposed)
    # Close every staging handle before rename, including on FUSE.
    current, info = _local(parent, name)
    if current != expected_raw or _identity(info) != _identity(expected_info):
        raise RuntimeError('Saved settings changed during staging')
    os.replace(staging, name, src_dir_fd=parent, dst_dir_fd=parent)
    os.fsync(parent)
    if _local(parent, name)[0] != proposed:
        raise RuntimeError('Saved settings replacement acknowledgement uncertain')


def stage_preview(*, source, config, control_root, expected_control_identity,
                  expected_config_sha256, proposed_config, settings):
    """Fresh source backup/parity + settings/binding, with no service actions.

    Requires a new empty private control root. Fresh stopped-writer JSON, rather
    than the earlier running observation, becomes the migration source. The
    expected original settings digest is mandatory; user edits are never merged
    or overwritten silently. Partial roots are retained and cannot be retried.
    """
    source, config, root = (Path(_canonical(str(p))) for p in (source, config, control_root))
    if source == config or root in source.parents or root in config.parents:
        raise RuntimeError('Separate source/settings/control paths required')
    values = dict(settings)
    if (values.get('STATE_FILE') != str(source) or values.get('WEB_CONFIG_FILE') != str(config)
            or values.get('SQLITE_STATE_FILE') != str(root / 'release' / 'state.db')):
        raise RuntimeError('Install paths must match preview environment')
    proposed = _encode(proposed_config)
    from app.config_store import KEYS, DEFAULTS
    effective = {**{key: DEFAULTS.get(key, '') for key in KEYS}, **values,
                 **{key: str(value) for key, value in proposed_config.items() if key in KEYS}}
    policy, _, _, _ = _policy(effective)
    _roots(policy, expected_control_identity)
    revision = _revision()
    with ExitStack() as stack:
        control = _private_root(root, expected_control_identity); stack.callback(os.close, control)
        if os.listdir(control):
            raise RuntimeError('New empty install control directory required')
        settings_parent = _open_directory(str(config.parent)); stack.callback(os.close, settings_parent)
        source_parent = _open_directory(str(source.parent)); stack.callback(os.close, source_parent)
        original_config, config_info = _local(settings_parent, config.name)
        if _sha(original_config) != expected_config_sha256:
            raise RuntimeError('Reviewed saved settings changed')
        original_source, _ = _local(source_parent, source.name)
        request = {'schema_version': 1, 'source_revision': revision,
            'request_id': secrets.token_hex(32), 'source_sha256': _sha(original_source),
            'original_config_sha256': _sha(original_config), 'preview_config_sha256': _sha(proposed),
            'control_identity': list(expected_control_identity), 'service_actions_performed': False,
            'media_actions_authorized': False}
        _write_private(control, REQUEST, _encode(request))
        _write_private(control, CONFIG_BACKUP, original_config)
        _write_private(control, CONFIG_PROPOSED, proposed)
        _boundary('after_request')
        prepare_release_state(source=source, control_directory=root / 'release',
                              expected_source_sha256=request['source_sha256'])
        _boundary('after_preparation')
        # Recheck the mounted private root and the freshly retained source before
        # changing settings. The prepare helper already verifies full SQL parity.
        check = _private_root(root, expected_control_identity); os.close(check)
        if _local(source_parent, source.name)[0] != original_source:
            raise RuntimeError('Fresh source changed before binding')
        _replace_config(settings_parent, config.name, original_config, config_info, proposed)
        _boundary('after_config')
        create_preview_binding(settings=values)
        _boundary('after_binding')
        validate_preview_activation(settings=values)
        check = _private_root(root, expected_control_identity); os.close(check)
        if _local(source_parent, source.name)[0] != original_source:
            raise RuntimeError('Fresh source changed after binding')
        report = {**request, 'status': 'offline_preview_install_prepared',
            'database_revision': 0, 'source_json_unchanged': True,
            'original_settings_backed_up': True, 'automatic_restoration': False}
        _write_private(control, COMPLETE, _encode(report))
        return report


def restore_original_settings(*, source, config, control_root, expected_control_identity):
    """Restore settings only if prepared SQL and retained JSON still agree at 0.

    Call only with both original and preview auditor writers stopped. A changed
    source, advanced SQL, pending operation or changed settings blocks recovery.
    Never substitute an old tracking backup, delete SQL or start the old worker.
    """
    source, config, root = (Path(_canonical(str(p))) for p in (source, config, control_root))
    with ExitStack() as stack:
        control = _private_root(root, expected_control_identity); stack.callback(os.close, control)
        original, _ = _local(control, CONFIG_BACKUP)
        proposed, _ = _local(control, CONFIG_PROPOSED)
        request = parse_unique_json(_local(control, REQUEST)[0])
        if (request.get('control_identity') != list(expected_control_identity)
                or request.get('original_config_sha256') != _sha(original)
                or request.get('preview_config_sha256') != _sha(proposed)):
            raise RuntimeError('Install recovery binding mismatch')
        parent = _open_directory(str(config.parent)); stack.callback(os.close, parent)
        current, info = _local(parent, config.name)
        if current not in (original, proposed):
            raise RuntimeError('Changed settings require manual recovery review')
        with _prepared_snapshot(source, root / 'release') as (_, snapshot, revision, _, verify):
            if revision != 0:
                raise RuntimeError('Advanced SQLite requires current-state export recovery')
            source_parent = _open_directory(str(source.parent)); stack.callback(os.close, source_parent)
            retained_source = _local(source_parent, source.name)[0]
            if (_sha(retained_source) != request['source_sha256']
                    or snapshot != parse_unique_json(retained_source)):
                raise RuntimeError('Original tracking source changed')
            receipt = {'status': 'original_settings_restored_not_started', 'database_revision': 0,
                'source_json_unchanged': True, 'service_actions_performed': False,
                'media_actions_authorized': False, 'automatic_restoration': False}
            _write_private(control, ROLLBACK_REQUEST, _encode(receipt))
            verify()
            if current != original:
                _replace_config(parent, config.name, current, info, original)
            verify()
            _write_private(control, ROLLBACK_COMPLETE, _encode(receipt))
            return receipt


def read_install_packet(*, directory, expected_identity, preview_image):
    """Reconstruct private outputs from original inputs; never trust argv edits."""
    from app import sqlite_preview_cutover as packet
    path = Path(_canonical(str(directory)))
    parent = _private_root(path, expected_identity)
    try:
        report = parse_unique_json(_local(parent, packet.REPORT_FILE)[0])
        originals = {name: _local(parent, name)[0] for name in packet.INPUTS}
        hashes = report.get('input_sha256')
        if not isinstance(hashes, dict) or any(hashes.get(name) != _sha(raw) for name, raw in originals.items()):
            raise RuntimeError('Private packet inputs changed')
        if report.get('managed_template') == 'captured_for_review':
            if hashes.get('original-template.xml') != _sha(_local(parent, 'original-template.xml')[0]):
                raise RuntimeError('Managed template capture changed')
        if report.get('preview_image_id') != preview_image or report.get('source_revision') != _revision():
            raise RuntimeError('Exact reviewed preview image/revision required')
        _, plan, env, proposed = packet.render_plan(original=parse_unique_json(originals[packet.INPUTS[0]]),
            saved=parse_unique_json(originals[packet.INPUTS[1]]), source=parse_unique_json(originals[packet.INPUTS[2]]),
            preview_image=preview_image, rollback_image=report['original_image_id'],
            control_host=report['control_host_path'], source_revision=_revision())
        plan['input_sha256'] = hashes
        if (parse_unique_json(_local(parent, packet.SPEC_FILE)[0]) != plan
                or _local(parent, packet.CONFIG_FILE)[0] != _encode(proposed)
                or _local(parent, packet.ENV_FILE)[0] != ''.join(k + '=' + v + '\n' for k, v in sorted(env.items())).encode()):
            raise RuntimeError('Private generated deployment plan changed')
        check = _private_root(path, expected_identity); os.close(check)
        return report, env, proposed
    finally:
        os.close(parent)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('action', choices=('stage', 'restore-settings'))
    parser.add_argument('--packet-directory', required=True)
    parser.add_argument('--expected-packet-identity', required=True)
    parser.add_argument('--control-root', required=True)
    parser.add_argument('--expected-control-identity', required=True)
    parser.add_argument('--preview-image', required=True)
    args = parser.parse_args()
    try:
        def identity(value):
            if not re.fullmatch('[0-9]+:[0-9]+', value):
                raise ValueError('Explicit device:inode required')
            return tuple(int(part) for part in value.split(':'))
        reviewed, env, proposed = read_install_packet(directory=args.packet_directory,
            expected_identity=identity(args.expected_packet_identity), preview_image=args.preview_image)
        if any(os.environ.get(key) != value for key, value in env.items()):
            raise RuntimeError('Reviewed container environment required')
        if (args.control_root != '/sqlite-control' or env['SQLITE_STATE_FILE'] != '/sqlite-control/release/state.db'
                or env['STATE_FILE'] != '/app/logs/auditor_state.json'
                or env['WEB_CONFIG_FILE'] != '/app/logs/auditor_config.json'):
            raise RuntimeError('Reviewed production bind layout required')
        common = dict(source=env['STATE_FILE'], config=env['WEB_CONFIG_FILE'], control_root=args.control_root,
                      expected_control_identity=identity(args.expected_control_identity))
        if args.action == 'stage':
            report = stage_preview(**common, expected_config_sha256=reviewed['input_sha256']['original-config.json'],
                                   proposed_config=proposed, settings=env)
        else:
            report = restore_original_settings(**common)
    except Exception as error:
        print(json.dumps({'status': 'offline_preview_install_blocked', 'failure_category': type(error).__name__,
            'automatic_restoration': False, 'service_actions_performed': False, 'media_actions_authorized': False}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
