"""Compare latest exported JSON with RO media and GET-only services; no worker."""
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from app.sqlite_json import parse_unique_json
from app.json_readonly_scan import rehearse_scan
from scripts.unraid_live_update_backup import load_backup_payloads


def run(*, comparison, backup, fingerprint):
    comparison, backup = Path(comparison), Path(backup)
    info = backup.stat(follow_symlinks=False)
    payloads, receipt = load_backup_payloads(directory=backup,
        expected_identity=(info.st_dev,info.st_ino),expected_fingerprint=fingerprint)
    manifest = parse_unique_json((comparison/'comparison-complete.json').read_bytes())
    source = comparison/'auditor_state.json'
    raw = source.read_bytes()
    claims = (comparison/'scan-claims-archive.json').read_bytes()
    if (manifest.get('status') != 'offline_json_comparison_prepared'
            or manifest.get('backup_fingerprint') != fingerprint
            or raw != payloads['tracking-snapshot.json'] or claims != payloads['daily-claims.json']
            or manifest.get('source_snapshot_revision') != receipt['snapshot_revision']
            or manifest.get('sha256') != {'auditor_state.json':hashlib.sha256(raw).hexdigest(),
                'scan-claims-archive.json':hashlib.sha256(claims).hexdigest()}):
        raise RuntimeError('Comparison does not match selected backup')
    container = parse_unique_json(payloads['current.inspect.json'])
    entries = container['Config']['Env']
    settings = dict(entry.split('=',1) for entry in entries)
    if len(settings) != len(entries): raise ValueError('Unique environment settings required')
    saved = parse_unique_json(payloads['saved-config.json'])
    if not isinstance(saved,dict) or any(not isinstance(v,str) for v in saved.values()):
        raise ValueError('Saved settings must be strings')
    settings.update(saved)
    result = rehearse_scan(state_file=source,settings=settings)
    if source.read_bytes() != raw or (comparison/'scan-claims-archive.json').read_bytes() != claims:
        raise RuntimeError('Comparison changed during rehearsal')
    counts = Counter(row.reason for row in result['decisions'])
    return {'status':'json_readonly_rehearsal_observed','comparison_only':True,
        'source_snapshot_revision':receipt['snapshot_revision'],
        'scanned_titles':result['scanned_titles'],'library_status':result['library_status'],'inventory_issues':result['inventory_issues'],
        'proposed_moves':[asdict(row) for row in result['moves']],
        'decision_reason_counts':dict(sorted(counts.items())),
        'clock_proposals':len(result['clock_proposals']),
        'ignored_housekeeping_entries':result['ignored_housekeeping_entries'],
        'tracking_bytes_unchanged':True,'scan_claims_unchanged':True,
        'media_actions_performed':False,'arr_updates_sent':0,
        'production_services_changed':False,'freshness_verified':False,
        'backup_freshness_verified':False,'external_writers_excluded':False,
        'settings_basis':'selected_backup','worker_configured':False}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comparison',required=True)
    parser.add_argument('--backup',required=True)
    parser.add_argument('--fingerprint',required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(comparison=args.comparison,backup=args.backup,fingerprint=args.fingerprint),sort_keys=True))
        return 0
    except Exception as error:
        reason = {
            'Comparison does not match selected backup':'comparison_backup_mismatch',
            'Stage changed during rehearsal':'inventory_changed',
            'Inventory changed during rehearsal':'inventory_changed',
            'TV content changed during rehearsal':'tv_content_changed',
            'Pending operation requires review':'pending_operation_requires_review',
            'Rehearsal deadline exceeded':'deadline_exceeded',
            'Read-only collection deadline exceeded':'deadline_exceeded',
        }.get(str(error),'input_or_collection_unavailable')
        print(json.dumps({'status':'json_readonly_rehearsal_blocked','comparison_only':True,
            'media_actions_performed':False,'arr_updates_sent':0,'production_services_changed':False,
            'automatic_retry':False,'reason':reason}))
        return 2


if __name__ == '__main__': raise SystemExit(main())
