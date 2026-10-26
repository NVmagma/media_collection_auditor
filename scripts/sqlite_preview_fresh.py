"""Initialize ONLY new private preview files from a verified prior settings packet.

Old state is not read into the new database, rewritten or removed. No service,
Docker, network or template installation commands run here. Partial destinations
are retained and refused on a later attempt.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re

from app.sqlite_disposable_restore import _write_private
from app.sqlite_json import parse_unique_json
from app.sqlite_preview_activation import _revision, validate_preview_activation
from app.sqlite_preview_cutover import INPUTS, render_plan
from app.sqlite_preview_install import _private_root, stage_preview
from app.sqlite_preview_template import render_preview_template, bind_published_reference
from app.sqlite_release_recovery import _encode, _local
from app.sqlite_scheduled_paths import scan_held_directory
from app.sqlite_state import SECTIONS, validate_snapshot
from scripts.sqlite_preview_release_request import fingerprint


def settings_from_packet(directory, identity, expected_fingerprint):
    fd = _private_root(Path(directory), identity)
    try:
        report = parse_unique_json(_local(fd, 'review.json')[0])
        if fingerprint(report) != expected_fingerprint:
            raise RuntimeError('Prior reviewed settings fingerprint mismatch')
        names = (*INPUTS, 'original-template.xml')
        inputs = {name: _local(fd, name)[0] for name in names}
        if report['input_sha256'] != {name: hashlib.sha256(raw).hexdigest() for name, raw in inputs.items()}:
            raise RuntimeError('Prior settings packet inputs changed')
        original = parse_unique_json(inputs['original.inspect.json'])
        saved = parse_unique_json(inputs['original-config.json'])
        _, _, env, proposed = render_plan(original=original, saved=saved,
            source=parse_unique_json(inputs['source-observed.json']),
            preview_image=report['preview_image_id'], rollback_image=report['original_image_id'],
            control_host=report['control_host_path'], source_revision=report['source_revision'])
        expected_env = ''.join(key+'='+value+'\n' for key,value in sorted(env.items())).encode()
        if (_local(fd, 'preview.env')[0] != expected_env
                or _local(fd, 'proposed-config.json')[0] != _encode(proposed)):
            raise RuntimeError('Prior proposed settings changed')
        return original, saved, env, proposed, inputs['original-template.xml']
    finally:
        os.close(fd)


def previous_tracking(directory, identity, expected_fingerprint):
    settings_from_packet(directory, identity, expected_fingerprint)
    fd = _private_root(Path(directory), identity)
    try:
        report = parse_unique_json(_local(fd, 'review.json')[0])
        if fingerprint(report) != expected_fingerprint: raise RuntimeError('Prior tracking selection changed')
        raw = _local(fd, 'source-observed.json')[0]
        if hashlib.sha256(raw).hexdigest() != report['input_sha256']['source-observed.json']:
            raise RuntimeError('Prior tracking snapshot changed')
        state = parse_unique_json(raw)
        validate_snapshot(state)
        return state
    finally:
        os.close(fd)


def prepare(*, packet, packet_identity, expected_fingerprint, logs, logs_identity,
            control, control_identity, host_logs, host_control, image_id, reference, tracking_mode="empty"):
    # Check all policy/reference/packet inputs before the first destination write.
    if not re.fullmatch('sha256:[0-9a-f]{64}', image_id): raise ValueError('Exact image ID required')
    original, saved, env, proposed, original_xml = settings_from_packet(packet, packet_identity, expected_fingerprint)
    if tracking_mode not in ('empty', 'restore-previous'): raise ValueError('Known tracking mode required')
    fresh = (previous_tracking(packet, packet_identity, expected_fingerprint)
             if tracking_mode == 'restore-previous' else {section: {} for section in SECTIONS})
    fresh_original = json.loads(json.dumps(original))
    for mount in fresh_original[0]['Mounts']:
        if mount['Destination'] == '/app/logs': mount['Source'] = host_logs
    report, plan, env, proposed = render_plan(original=fresh_original, saved=saved, source=fresh,
        preview_image=image_id, rollback_image=fresh_original[0]['Image'],
        control_host=host_control, source_revision=_revision())
    xml, _ = render_preview_template(original=original_xml, env=env, plan=plan, review=report)
    xml = bind_published_reference(proposed=xml, reference=reference)
    logs, control = Path(logs), Path(control)
    if (str(logs) != '/app/logs' or str(control) != '/sqlite-control'):
        raise RuntimeError('Fresh preparation requires fixed private container binds')
    if logs_identity == control_identity or logs_identity == packet_identity or control_identity == packet_identity:
        raise RuntimeError('Disjoint new private directories required')
    with ExitStack() as stack:
        log_fd = _private_root(logs, logs_identity); stack.callback(os.close, log_fd)
        control_fd = _private_root(control, control_identity); stack.callback(os.close, control_fd)
        for fd in (log_fd, control_fd):
            with scan_held_directory(fd) as entries:
                if next(entries, None) is not None: raise RuntimeError('Fresh destinations must be empty')
        _write_private(log_fd, 'fresh-request.json', _encode({
            'source_revision': _revision(), 'image_id': image_id, 'reference': reference,
            'settings_fingerprint': expected_fingerprint, 'old_tracking_imported': tracking_mode == 'restore-previous',
            'media_actions_authorized': False}))
        _write_private(log_fd, 'auditor_state.json', _encode(fresh))
        config_raw = _encode(proposed)
        _write_private(log_fd, 'auditor_config.json', config_raw)
        stage_preview(source=logs/'auditor_state.json', config=logs/'auditor_config.json',
            control_root=control, expected_control_identity=control_identity,
            expected_config_sha256=hashlib.sha256(config_raw).hexdigest(),
            proposed_config=proposed, settings=env)
        validate_preview_activation(settings=env)
        _write_private(log_fd, 'runtime.env', ''.join(key+'='+value+'\n' for key,value in sorted(env.items())).encode())
        _write_private(log_fd, 'fresh-template.xml', xml)
        result = {'status': 'fresh_sqlite_preview_prepared', 'image_id': image_id,
            'reference': reference, 'source_revision': _revision(),
            'host_logs': host_logs, 'host_control': host_control,
            'tracking_counts': {section: len(fresh[section]) for section in SECTIONS},
            'tracking_counts_by_library': {library: {section: sum(key.startswith('TV/') == (library == 'TV') for key in fresh[section]) for section in SECTIONS} for library in ('Movies','TV')},
            'old_tracking_imported': tracking_mode == 'restore-previous', 'media_actions_authorized': False,
            'service_actions_performed': False, 'automatic_restoration': False}
        _write_private(log_fd, 'fresh-complete.json', _encode(result))
        return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ('packet','packet-identity','fingerprint','logs-identity','control-identity',
                 'host-logs','host-control','image-id','reference'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--tracking-mode', choices=('empty','restore-previous'), default='empty')
    args = parser.parse_args()
    def identity(value):
        if not re.fullmatch('[0-9]+:[0-9]+',value): raise ValueError('Directory identity required')
        return tuple(map(int,value.split(':')))
    try:
        result = prepare(packet=args.packet, packet_identity=identity(args.packet_identity),
            expected_fingerprint=args.fingerprint, logs='/app/logs', logs_identity=identity(args.logs_identity),
            control='/sqlite-control', control_identity=identity(args.control_identity),
            host_logs=args.host_logs, host_control=args.host_control, image_id=args.image_id, reference=args.reference,
            tracking_mode=args.tracking_mode)
    except Exception as error:
        print(json.dumps({'status':'fresh_preparation_blocked', 'failure_category':type(error).__name__,
            'service_actions_performed':False,'media_actions_authorized':False}))
        return 1
    print(json.dumps(result))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
