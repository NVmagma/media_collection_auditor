"""New private logical live backup, including byte-exact daily claims.

Observation only: never changes the current service, SQLite, claims or settings.
Partial packets remain incomplete and cannot be reused. A later handoff must
revalidate the complete capture after stopping the original worker.
"""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from app.sqlite_disposable_restore import _write_private
from app.sqlite_json import parse_unique_json
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_preview_install import _private_root
from app.sqlite_release_preparation import _identity
from app.sqlite_release_recovery import _encode, _local
from app.sqlite_scheduled_paths import _open_directory, scan_held_directory
from app.sqlite_state import SECTIONS, validate_snapshot

FILES = ('current.inspect.json', 'current-template.xml', 'saved-config.json',
         'retained-source.json', 'current-binding.json', 'tracking-snapshot.json',
         'daily-claims.json')
CLAIM_NAME = re.compile(r'[0-9a-f]{64}\.json')
MAX_CLAIMS = 10000
MAX_CLAIM_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024


def _boundary(phase):
    """Fault injection seam with no production side effects."""


def read_daily_claims(control):
    """Retain even empty/partial claims; their existence prevents replay.

    No JSON interpretation, repair, filtering by date or deletion is allowed.
    No-follow descriptors and identities detect replaced directories/entries.
    """
    root = _open_directory(str(control))
    child = None
    try:
        root_identity = _identity(os.fstat(root))[:2]
        try:
            child = os.open('.sqlite_scheduled_slots', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        except FileNotFoundError:
            return {'present': False, 'entries': {}}, ('absent', root_identity)
        info = os.fstat(child)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError('Private daily claim directory required')
        rows, identities, total = {}, {}, 0
        with scan_held_directory(child) as entries:
            names = sorted(entry.name for entry in entries)
        if len(names) > MAX_CLAIMS or any(CLAIM_NAME.fullmatch(name) is None for name in names):
            raise RuntimeError('Bounded recognized daily claim names required')
        for name in names:
            claim_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=child)
            try:
                entry = os.fstat(claim_fd)
                if (not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1
                        or entry.st_size > MAX_CLAIM_BYTES):
                    raise RuntimeError('Bounded regular daily claim required')
                chunks = bytearray()
                while len(chunks) <= MAX_CLAIM_BYTES:
                    chunk = os.read(claim_fd, min(65536, MAX_CLAIM_BYTES + 1 - len(chunks)))
                    if not chunk:
                        break
                    chunks.extend(chunk)
                raw = bytes(chunks)
                if (_identity(os.fstat(claim_fd)) != _identity(entry)
                        or _identity(os.stat(name, dir_fd=child, follow_symlinks=False)) != _identity(entry)
                        or len(raw) != entry.st_size):
                    raise RuntimeError('Daily claim changed during read')
            finally:
                os.close(claim_fd)
            if (not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1
                    or entry.st_uid != os.geteuid() or stat.S_IMODE(entry.st_mode) != 0o600
                    or len(raw) > MAX_CLAIM_BYTES):
                raise RuntimeError('Private regular daily claim required')
            total += len(raw)
            if total > MAX_TOTAL_BYTES:
                raise RuntimeError('Daily claim byte limit exceeded')
            rows[name] = base64.b64encode(raw).decode('ascii')
            identities[name] = _identity(entry)
        if sorted(os.listdir(child)) != names:
            raise RuntimeError('Daily claim inventory changed')
        for name in names:
            if _identity(os.stat(name, dir_fd=child, follow_symlinks=False)) != identities[name]:
                raise RuntimeError('Daily claim changed')
        if _identity(os.stat('.sqlite_scheduled_slots', dir_fd=root, follow_symlinks=False)) != _identity(info):
            raise RuntimeError('Daily claim directory changed')
        reopened = _open_directory(str(control))
        try:
            if _identity(os.fstat(reopened))[:2] != root_identity:
                raise RuntimeError('Control directory changed')
        finally:
            os.close(reopened)
        return {'present': True, 'entries': rows}, (root_identity, _identity(info), identities)
    finally:
        if child is not None:
            os.close(child)
        os.close(root)


def _validate_claim_payload(value):
    if (not isinstance(value, dict) or set(value) != {'present', 'entries'}
            or type(value['present']) is not bool or not isinstance(value['entries'], dict)
            or len(value['entries']) > MAX_CLAIMS or (not value['present'] and value['entries'])):
        raise ValueError('Complete daily claim inventory required')
    total = 0
    for name, encoded in value['entries'].items():
        if not isinstance(name, str) or CLAIM_NAME.fullmatch(name) is None or not isinstance(encoded, str):
            raise ValueError('Recognized daily claim encoding required')
        raw = base64.b64decode(encoded, validate=True)
        if base64.b64encode(raw).decode('ascii') != encoded or len(raw) > MAX_CLAIM_BYTES:
            raise ValueError('Bounded canonical daily claim encoding required')
        total += len(raw)
    if total > MAX_TOTAL_BYTES:
        raise ValueError('Daily claim byte limit exceeded')


def capture_backup(*, directory, expected_identity, container, template, source_revision,
                   validate_current, read_snapshot, read_inputs, read_claims):
    if (not re.fullmatch('[0-9a-f]{40}', source_revision or '')
            or container.get('Name') != '/media_collection_auditor'
            or not re.fullmatch('[0-9a-f]{64}', container.get('Id', ''))
            or not re.fullmatch('sha256:[0-9a-f]{64}', container.get('Image', ''))):
        raise ValueError('Exact current live image and container required')
    validate_current()
    state, revision = read_snapshot()
    validate_snapshot(state)
    if type(revision) is not int or revision < 0 or INTENTS_KEY in state:
        raise RuntimeError('Verified live state without pending operations required')
    before = read_inputs()
    claims, claim_identity = read_claims()
    _validate_claim_payload(claims)
    if set(before) != {'saved-config.json', 'retained-source.json', 'current-binding.json'}:
        raise ValueError('Complete private live inputs required')
    payloads = {name: raw for name, (raw, _) in before.items()}
    payloads.update({'current.inspect.json': _encode(container), 'current-template.xml': template,
                     'tracking-snapshot.json': _encode(state), 'daily-claims.json': _encode(claims)})
    if any(not isinstance(raw, bytes) or len(raw) > 64 * 1024 * 1024 for raw in payloads.values()):
        raise ValueError('Bounded private backup required')
    packet = Path(directory)
    fd = _private_root(packet, expected_identity)
    try:
        if os.listdir(fd):
            raise RuntimeError('New empty backup required; no replay or overwrite')
        _write_private(fd, 'backup-request.json', _encode({'schema_version': 1,
            'kind': 'live_update', 'source_revision': source_revision,
            'container_id': container['Id'], 'image_id': container['Image']}))
        _boundary('after_request')
        for name in FILES:
            _write_private(fd, name, payloads[name])
            _boundary('after_' + name)
        def verify():
            validate_current()
            if (read_snapshot() != (state, revision) or read_inputs() != before
                    or read_claims() != (claims, claim_identity)):
                raise RuntimeError('Current live state or daily claims changed during capture')
            reopened = _private_root(packet, expected_identity)
            os.close(reopened)
            if any(_local(fd, name)[0] != payloads[name] for name in FILES):
                raise RuntimeError('Private packet changed during capture')
        verify()
        _boundary('before_completion')
        verify()
        receipt = {'schema_version': 1, 'status': 'live_update_backup_captured',
            'backup_kind': 'logical_live_tracking_settings_and_daily_claims',
            'captured_at': datetime.now(timezone.utc).isoformat(), 'source_revision': source_revision,
            'container_id': container['Id'], 'image_id': container['Image'],
            'snapshot_revision': revision, 'daily_claim_count': len(claims['entries']),
            'request_sha256': hashlib.sha256(_local(fd, 'backup-request.json')[0]).hexdigest(),
            'sha256': {name: hashlib.sha256(raw).hexdigest() for name, raw in payloads.items()},
            'tracking_counts': {key: len(state.get(key, {})) for key in SECTIONS},
            'service_changes_performed': False, 'media_actions_authorized': False,
            'update_authorized': False, 'automatic_restoration': False,
            'backup_freshness_verified': False}
        _write_private(fd, 'backup-complete.json', _encode(receipt))
        return {key: value for key, value in receipt.items() if key not in ('sha256', 'request_sha256')}
    finally:
        os.close(fd)


def inspect_backup(*, directory, expected_identity, expected_fingerprint):
    """Verify the exact selected packet; never authorize installation or replay."""
    if not re.fullmatch('[0-9a-f]{64}', expected_fingerprint or ''):
        raise ValueError('Exact backup fingerprint required')
    fd = _private_root(Path(directory), expected_identity)
    try:
        if set(os.listdir(fd)) != set(FILES) | {'backup-request.json', 'backup-complete.json'}:
            raise RuntimeError('Complete recognized live backup required')
        raw = _local(fd, 'backup-complete.json')[0]
        if hashlib.sha256(raw).hexdigest() != expected_fingerprint:
            raise RuntimeError('Selected live backup fingerprint changed')
        receipt = parse_unique_json(raw)
        if (type(receipt.get('schema_version')) is not int or receipt['schema_version'] != 1 or receipt.get('status') != 'live_update_backup_captured'
                or type(receipt.get('snapshot_revision')) is not int or receipt['snapshot_revision'] < 0
                or receipt.get('update_authorized') is not False or receipt.get('automatic_restoration') is not False
                or set(receipt.get('sha256', {})) != set(FILES)):
            raise RuntimeError('Recognized live backup receipt required')
        request = _local(fd, 'backup-request.json')[0]
        if hashlib.sha256(request).hexdigest() != receipt.get('request_sha256'):
            raise RuntimeError('Live backup request changed')
        request_value = parse_unique_json(request)
        if request_value != {'schema_version': 1, 'kind': 'live_update',
                'source_revision': receipt.get('source_revision'),
                'container_id': receipt.get('container_id'), 'image_id': receipt.get('image_id')}:
            raise RuntimeError('Live backup provenance mismatch')
        payloads = {name: _local(fd, name)[0] for name in FILES}
        if any(hashlib.sha256(value).hexdigest() != receipt['sha256'][name] for name, value in payloads.items()):
            raise RuntimeError('Live backup payload changed')
        state = parse_unique_json(payloads['tracking-snapshot.json'])
        validate_snapshot(state)
        if INTENTS_KEY in state:
            raise RuntimeError('Pending operation cannot be migrated')
        claims = parse_unique_json(payloads['daily-claims.json'])
        _validate_claim_payload(claims)
        if (len(claims['entries']) != receipt.get('daily_claim_count')
                or {key: len(state.get(key, {})) for key in SECTIONS} != receipt.get('tracking_counts')):
            raise RuntimeError('Live backup summary mismatch')
        return {'status': 'live_update_backup_verified', 'snapshot_revision': receipt['snapshot_revision'],
                'daily_claim_count': len(claims['entries']), 'update_authorized': False,
                'automatic_restoration': False, 'read_only': True}
    finally:
        os.close(fd)


def capture_current(*, directory, expected_identity, container, templates):
    """Run in the CURRENT image, using its packaged live validator/profile.

    The template is captured as a unique inventory input, not certified as a
    recreation recipe. The later proposal must validate its complete parity.
    """
    from app.sqlite_live_binding import validate_live_binding, _revision, BINDING
    from app.sqlite_tracking_view import _candidate_capture
    from app.unraid_update_review import matching_templates
    from scripts.unraid_update_backup import _local_read_path
    matches = matching_templates(templates)
    if len(matches) != 1:
        raise RuntimeError('One unambiguous current managed template required')
    template = next(raw for name, raw in templates if name == matches[0][0])
    entries = container['Config']['Env']
    settings = dict(item.split('=', 1) for item in entries)
    if len(settings) != len(entries):
        raise ValueError('Unique environment keys required')
    database = Path(settings.get('SQLITE_STATE_FILE', ''))
    paths = {'saved-config.json': Path(settings.get('WEB_CONFIG_FILE', '/app/logs/auditor_config.json')),
             'retained-source.json': Path(settings.get('STATE_FILE', '/app/logs/auditor_state.json')),
             'current-binding.json': database.parent / BINDING}
    if any(not path.is_absolute() for path in (*paths.values(), database)):
        raise ValueError('Absolute live paths required')
    packet = Path(directory)
    for path in (*paths.values(), database.parent):
        if packet == path or packet in path.parents or path in packet.parents:
            raise ValueError('Disjoint new private backup required')
    def read_inputs():
        return {name: (raw, _identity(info)) for name, path in paths.items()
                for raw, info in [_local_read_path(path)]}
    def read_snapshot():
        with _candidate_capture(database) as capture:
            return capture.state, capture.revision
    return capture_backup(directory=packet, expected_identity=expected_identity,
        container=container, template=template, source_revision=_revision(),
        validate_current=lambda: validate_live_binding(settings=settings, for_execution=True),
        read_snapshot=read_snapshot, read_inputs=read_inputs,
        read_claims=lambda: read_daily_claims(database.parent))


def main():
    import argparse
    import sys
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--templates', required=True)
    args = parser.parse_args()
    try:
        if not re.fullmatch(r'[0-9]+:[0-9]+', args.identity):
            raise ValueError('Exact new packet identity required')
        identity = tuple(map(int, args.identity.split(':')))
        raw = sys.stdin.buffer.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('Bounded container input required')
        items = parse_unique_json(raw)
        if not isinstance(items, list) or len(items) != 1:
            raise ValueError('One selected current container required')
        folder = _open_directory(args.templates)
        try:
            names = sorted(name for name in os.listdir(folder) if name.endswith('.xml'))
            if len(names) > 1000:
                raise ValueError('Bounded template inventory required')
            templates = [(name, _local(folder, name)[0]) for name in names]
        finally:
            os.close(folder)
        result = capture_current(directory=args.directory, expected_identity=identity,
                                 container=items[0], templates=templates)
        fd = _private_root(Path(args.directory), identity)
        try:
            result['backup_fingerprint'] = hashlib.sha256(_local(fd, 'backup-complete.json')[0]).hexdigest()
        finally:
            os.close(fd)
    except Exception as error:
        print(json.dumps({'status': 'live_update_backup_blocked',
            'error_type': type(error).__name__, 'automatic_action': 'none',
            'service_changes_performed': False, 'media_actions_authorized': False,
            'partial_files_retained': True}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
