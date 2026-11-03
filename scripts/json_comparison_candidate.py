"""Prepare offline JSON comparison inputs from a verified live backup.

Never selects a backend, starts a worker, edits originals or authorizes media
operations. An incomplete candidate is retained and must not be activated.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from app.sqlite_json import parse_unique_json
from scripts.unraid_live_update_backup import load_backup_payloads


def _write(directory, name, raw):
    fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def prepare_candidate(*, backup, backup_identity, fingerprint, parent):
    backup, parent = Path(backup), Path(parent)
    if (not parent.is_absolute() or parent.is_symlink() or parent.resolve() != parent
            or not parent.is_dir() or parent == backup or backup in parent.parents
            or parent in backup.parents):
        raise ValueError('Disjoint canonical comparison parent required')
    payloads, receipt = load_backup_payloads(directory=backup,
        expected_identity=backup_identity, expected_fingerprint=fingerprint)
    # Use the latest logical snapshot, never retained-source.json (the old JSON).
    raw = payloads['tracking-snapshot.json']
    state = parse_unique_json(raw)
    if state.get('arr_sync_pending'):
        raise ValueError('Resolve pending Arr updates before comparison')
    root = Path(tempfile.mkdtemp(prefix='auditor-json-comparison.', dir=parent))
    files = {'auditor_state.json': raw,
             'scan-claims-archive.json': payloads['daily-claims.json']}
    for name, data in files.items():
        _write(root, name, data)
    report = {'status': 'offline_json_comparison_prepared', 'schema_version': 1,
        'source_snapshot_revision': receipt['snapshot_revision'],
        'backup_fingerprint': fingerprint,
        'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        'tracking_counts': {key: len(state.get(key, {})) for key in
            ('first_seen', 'queued', 'in_removal', 'keep_seen', 'arr_sync_pending')},
        'comparison_only': True, 'production_services_changed': False,
        'media_actions_authorized': False, 'worker_configured': False,
        'claims_archived_not_activated': True, 'freshness_verified': False}
    _write(root, 'comparison-complete.json', (json.dumps(report, sort_keys=True)+'\n').encode())
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
    return root, report


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--fingerprint', required=True)
    parser.add_argument('--comparison-parent', required=True)
    args = parser.parse_args()
    try:
        info = Path(args.backup).stat(follow_symlinks=False)
        root, report = prepare_candidate(backup=args.backup,
            backup_identity=(info.st_dev, info.st_ino), fingerprint=args.fingerprint,
            parent=args.comparison_parent)
        print('Private comparison directory: ' + str(root))
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'status': 'json_comparison_blocked',
            'production_services_changed': False, 'media_actions_authorized': False,
            'partial_files_may_remain': True}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
