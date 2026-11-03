"""Compare latest exported JSON with RO media and GET-only services; no worker."""
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from app.sqlite_json import parse_unique_json
from app.json_readonly_scan import rehearse_scan
from scripts.unraid_live_update_backup import load_backup_payloads


def run(*, comparison, backup, fingerprint, local_only=False, observer=lambda stage: None):
    if type(local_only) is not bool: raise ValueError('Explicit rehearsal mode required')
    observer('backup_validation')
    comparison, backup = Path(comparison), Path(backup)
    info = backup.stat(follow_symlinks=False)
    payloads, receipt = load_backup_payloads(directory=backup,
        expected_identity=(info.st_dev,info.st_ino),expected_fingerprint=fingerprint)
    observer('comparison_validation')
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
    observer('captured_settings')
    from app.config_store import KEYS, DEFAULTS
    container = parse_unique_json(payloads['current.inspect.json'])
    entries = container['Config']['Env']
    settings = dict(entry.split('=',1) for entry in entries)
    if len(settings) != len(entries): raise ValueError('Unique environment settings required')
    saved = parse_unique_json(payloads['saved-config.json'])
    if not isinstance(saved,dict): raise ValueError('Saved settings object required')
    # Match the existing application's saved-config precedence and unknown-field handling.
    settings.update({key:str(value) for key,value in saved.items() if key in KEYS})
    for key in KEYS: settings.setdefault(key,DEFAULTS.get(key,''))
    observer('path_configuration')
    extra = {}
    if local_only:
        from app.json_lifecycle_plan import LibraryObservation, TitleObservation, plan_scan
        def local_plan(*,snapshot,inventories,now,maximum_titles,**unused):
            libraries = [LibraryObservation(lib.library,False,False,tuple(
                TitleObservation(('TV/' if lib.library == 'TV' else '')+row.folder,
                    row.stage,row.threshold_days,None,'unavailable',row.blocker) for row in lib.titles))
                for lib in inventories]
            return {**plan_scan(snapshot=snapshot,libraries=libraries,now=now,maximum_titles=maximum_titles),
                'library_status':tuple({'library':lib.library,'inventory_complete':lib.complete,
                    'titles':len(lib.titles) if lib.complete else None,'jellyfin_complete':False,
                    'arr_complete':False} for lib in inventories)}
        extra['collect'] = local_plan
    def scan_stage(stage):
        observer('local_advisory_planning' if local_only and stage == 'service_collection' else stage)
    result = rehearse_scan(state_file=source,settings=settings,observer=scan_stage,**extra)
    observer('result_verification')
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
        'settings_basis':'selected_backup','network_enabled':not local_only,
        'rehearsal_scope':'local_inventory_only' if local_only else 'inventory_and_get_services',
        'lifecycle_timezone':result['lifecycle_timezone'],
        'worker_configured':False}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comparison',required=True)
    parser.add_argument('--backup',required=True)
    parser.add_argument('--fingerprint',required=True)
    parser.add_argument('--local-only',action='store_true')
    args = parser.parse_args()
    stage = 'arguments'
    def observe(value):
        nonlocal stage
        stage = value
    try:
        print(json.dumps(run(comparison=args.comparison,backup=args.backup,fingerprint=args.fingerprint,local_only=args.local_only,observer=observe),sort_keys=True))
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
            'automatic_retry':False,'reason':reason,'diagnostic_stage':stage,
            'error_type':type(error).__name__ if type(error).__name__ in
                ('RuntimeError','ValueError','KeyError','TypeError','FileNotFoundError','PermissionError') else 'Error'}))
        return 2


if __name__ == '__main__': raise SystemExit(main())
