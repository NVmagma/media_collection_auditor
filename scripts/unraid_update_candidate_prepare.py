"""Prepare a different preview image's binding only; never build a service payload."""
import argparse
import json
import re
import sys
from scripts.unraid_update_prepare import prepare_replacement


def prepare_candidate(*, image, expected_image_id, backup, backup_identity, fingerprint,
                      logs, logs_identity, control, control_identity):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',expected_image_id or '') or image.get('Id')!=expected_image_id:
        raise ValueError('Exact selected candidate image required')
    result=prepare_replacement(backup=backup,backup_identity=backup_identity,backup_fingerprint=fingerprint,
        logs=logs,logs_identity=logs_identity,control=control,control_identity=control_identity,candidate_image=image)
    return {**result,'status':'candidate_files_prepared_not_started',
            'registry_reference_configured':False,'container_payload_prepared':False,
            'deployment_authorized':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    for key in ('image-id','backup','backup-identity','fingerprint','logs','logs-identity','control','control-identity'):
        parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    def identity(raw):
        if not re.fullmatch(r'[0-9]{1,20}:[0-9]{1,20}',raw):raise ValueError('Known directory identity required')
        return tuple(map(int,raw.split(':')))
    try:
        from app.sqlite_json import parse_unique_json
        raw=sys.stdin.buffer.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:raise ValueError('Bounded image metadata required')
        images=parse_unique_json(raw)
        if not isinstance(images,list) or len(images)!=1 or not isinstance(images[0],dict):raise ValueError('One selected image required')
        result=prepare_candidate(image=images[0],expected_image_id=args.image_id,
            backup=args.backup,backup_identity=identity(args.backup_identity),fingerprint=args.fingerprint,
            logs=args.logs,logs_identity=identity(args.logs_identity),control=args.control,control_identity=identity(args.control_identity))
    except Exception:
        print(json.dumps({'status':'candidate_preparation_blocked','partial_files_retained':True,
            'deployment_authorized':False,'service_changes_performed':False,'media_actions_authorized':False}))
        return 2
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
