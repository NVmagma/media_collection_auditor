"""Read-only source freshness check, run with the OLD image's packaged validator."""
import json
import os
from pathlib import Path
import re

from app.sqlite_json import parse_unique_json
from app.sqlite_release_recovery import _local
from app.sqlite_scheduled_paths import _open_directory
from scripts.unraid_live_update_backup import load_backup_payloads, read_daily_claims
from scripts.sqlite_preview_service import validate_original


def compare_source(*, payloads, receipt, current, validate, snapshot, inputs, claims):
    original = parse_unique_json(payloads['current.inspect.json'])
    validate_original(current, original, name='media_collection_auditor', running=current['State']['Running'])
    validate()
    before = (snapshot(), inputs(), claims())
    if (before[0] != (parse_unique_json(payloads['tracking-snapshot.json']), receipt['snapshot_revision'])
            or before[1] != {name: payloads[name] for name in
                            ('saved-config.json', 'retained-source.json', 'current-binding.json')}
            or before[2] != parse_unique_json(payloads['daily-claims.json'])):
        raise RuntimeError('Current source differs from selected backup')
    validate()
    if (snapshot(), inputs(), claims()) != before:
        raise RuntimeError('Source changed during observation')
    return dict(status='json_cutover_source_matches_backup', read_only=True,
                backup_matches_current_observation=True, writer_quiescence_verified=not current['State']['Running'],
                snapshot_revision=receipt['snapshot_revision'], service_changes_performed=False,
                media_actions_performed=False)


def main():
    import argparse, sys
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--backup-identity', required=True)
    parser.add_argument('--fingerprint', required=True)
    args = parser.parse_args()
    try:
        if not re.fullmatch(r'[0-9]+:[0-9]+', args.backup_identity): raise ValueError('Identity required')
        selected = dict(directory=Path('/backup'), expected_identity=tuple(map(int,args.backup_identity.split(':'))),
                        expected_fingerprint=args.fingerprint)
        payloads, receipt = load_backup_payloads(**selected)
        raw = sys.stdin.buffer.read(16*1024*1024+1)
        if len(raw)>16*1024*1024: raise ValueError('Bounded inspection required')
        items = parse_unique_json(raw)
        if not isinstance(items,list) or len(items)!=1: raise ValueError('One current container required')
        current = items[0]
        from app.sqlite_live_binding import validate_live_binding, BINDING, _revision
        from app.sqlite_tracking_view import _candidate_capture
        settings = dict(value.split('=',1) for value in current['Config']['Env'])
        if len(settings)!=len(current['Config']['Env']) or _revision()!=receipt['source_revision']:
            raise RuntimeError('Packaged source revision mismatch')
        database = Path(settings['SQLITE_STATE_FILE'])
        paths = {'saved-config.json':Path(settings.get('WEB_CONFIG_FILE','/app/logs/auditor_config.json')),
                 'retained-source.json':Path(settings.get('STATE_FILE','/app/logs/auditor_state.json')),
                 'current-binding.json':database.parent/BINDING}
        def inputs():
            values={}
            for name,path in paths.items():
                fd=_open_directory(str(path.parent))
                try: values[name]=_local(fd,path.name)[0]
                finally: os.close(fd)
            return values
        def snapshot():
            with _candidate_capture(database) as capture: return capture.state,capture.revision
        result=compare_source(payloads=payloads,receipt=receipt,current=current,
            validate=lambda:validate_live_binding(settings=settings,for_execution=True),snapshot=snapshot,
            inputs=inputs,claims=lambda:read_daily_claims(database.parent)[0])
        if load_backup_payloads(**selected)!=(payloads,receipt): raise RuntimeError('Backup changed')
        print(json.dumps(result,sort_keys=True)); return 0
    except Exception:
        print(json.dumps(dict(status='json_cutover_source_review_blocked', read_only=True,
            service_changes_performed=False,media_actions_performed=False,automatic_action='none'))); return 2

if __name__=='__main__': raise SystemExit(main())
