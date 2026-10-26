"""Private release selection verification; no publication or service controls.

The public fingerprint pins the reviewed input hashes, proposed template, exact
worker image and repository. It contains no credentials. A matching fingerprint
is a selection check, not human authorization to execute a deployment.
"""
import hashlib
import json
import os
from pathlib import Path
import re

from app.sqlite_preview_install import read_install_packet, _private_root
from app.sqlite_preview_cutover import INPUTS
from app.sqlite_release_recovery import _encode, _local
from app.sqlite_json import parse_unique_json

REPOSITORY = 'ghcr.io/nvmagma/media_collection_auditor'


def selection(report):
    for key in ('original_container_id', 'proposed_template_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', report.get(key, '')): raise ValueError('Exact reviewed identity required')
    for key in ('preview_image_id', 'original_image_id'):
        if not re.fullmatch('sha256:[0-9a-f]{64}', report.get(key, '')): raise ValueError('Exact reviewed image required')
    if not re.fullmatch('[0-9a-f]{40}', report.get('source_revision', '')): raise ValueError('Exact worker revision required')
    inputs = report.get('input_sha256')
    if (not isinstance(inputs, dict) or set(inputs) != set(INPUTS) | {'original-template.xml'}
            or any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value) for value in inputs.values())):
        raise ValueError('Complete reviewed private input digests required')
    return {'schema_version': 1, 'repository': REPOSITORY,
        'preview_image_id': report['preview_image_id'], 'worker_revision': report['source_revision'],
        'original_container_id': report['original_container_id'], 'original_image_id': report['original_image_id'],
        'input_sha256': inputs, 'proposed_template_sha256': report['proposed_template_sha256'],
        'control_host_path': report['control_host_path'], 'daily_time': report['daily_time'],
        'timezone': report['timezone'], 'enabled_libraries': report['enabled_libraries'],
        'published_ports': report['published_ports'], 'maximum_proposed_actions': report['maximum_proposed_actions']}


def fingerprint(report):
    return hashlib.sha256(_encode(selection(report))).hexdigest()


def verify(*, directory, expected_identity, image_id, expected_fingerprint, action):
    if action not in ('review', 'review-sha', 'reference', 'control-path'): raise ValueError('Known request operation required')
    report, env, proposed = read_install_packet(directory=directory, expected_identity=expected_identity, preview_image=image_id)
    if fingerprint(report) != expected_fingerprint: raise RuntimeError('Release selection differs from approved fingerprint')
    if (report.get('managed_template_plan') != 'prepared_not_installed' or report.get('network_mode') != 'bridge'
            or report.get('published_ports') != [{'container': '8080/tcp', 'host_ip': '', 'host_port': '8089'}]
            or report.get('control_host_path') != '/mnt/user/appdata/media_collection_auditor_sqlite_control'):
        raise RuntimeError('Reviewed initial Tower layout required')
    from app.config_store import KEYS, DEFAULTS
    from app.sqlite_preview_activation import _policy
    effective = {**{key: DEFAULTS.get(key, '') for key in KEYS}, **env,
                 **{key: str(value) for key, value in proposed.items() if key in KEYS}}
    policy, _, _, _ = _policy(effective)
    if ([item.name for item in policy.libraries] != ['Movies'] or policy.maximum_actions != 10
            or policy.schedule.local_time != '02:00' or policy.schedule.timezone_name != 'America/Los_Angeles'):
        raise RuntimeError('Reviewed initial Movies-only daily preview policy required')
    parent = _private_root(Path(directory), expected_identity)
    try:
        captured = parse_unique_json(_local(parent, 'original.inspect.json')[0])[0]
        mounts = {item['Destination']: item['Source'] for item in captured['Mounts']}
        if mounts != {'/media': '/mnt/user/media_storage', '/app/logs': '/mnt/user/appdata/media_collection_auditor'}:
            raise RuntimeError('Reviewed host bind sources required')
        review_sha = hashlib.sha256(_local(parent, 'review.json')[0]).hexdigest()
        if action == 'review-sha': return review_sha
        if action == 'control-path': return report['control_host_path']
        if action == 'reference':
            request = parse_unique_json(_local(parent, 'service-request.json')[0])
            reference = request.get('reference', '')
            if (not re.fullmatch(re.escape(REPOSITORY) + '@sha256:[0-9a-f]{64}', reference)
                    or request.get('context', {}).get('approved_review_sha256') != review_sha
                    or request.get('preview_image_id') != image_id):
                raise RuntimeError('Retained service request differs from approved selection')
            return reference
        return {'status': 'production_release_selection_verified_not_executed',
            'selection_fingerprint': expected_fingerprint, 'review_sha256': review_sha,
            'worker_revision': report['source_revision'], 'preview_image_id': image_id,
            'original_container_id': report['original_container_id'], 'repository': REPOSITORY,
            'registry_tag': REPOSITORY + ':sqlite-preview-' + report['source_revision'][:12] + '-' + image_id[7:],
            'daily_time': report['daily_time'], 'timezone': report['timezone'],
            'enabled_libraries': report['enabled_libraries'], 'published_ports': report['published_ports'],
            'execution_mode': 'scheduled_preview', 'media_read_only': True, 'media_actions_authorized': False,
            'service_actions_performed': False, 'registry_publication_performed': False}
    finally:
        os.close(parent)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('action', choices=('review', 'review-sha', 'reference', 'control-path'))
    parser.add_argument('--packet-directory', required=True)
    parser.add_argument('--packet-identity', required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--selection-fingerprint', required=True)
    args = parser.parse_args()
    try:
        if not re.fullmatch('[0-9]+:[0-9]+', args.packet_identity): raise ValueError('Device:inode required')
        value = verify(directory=args.packet_directory,
            expected_identity=tuple(int(part) for part in args.packet_identity.split(':')),
            image_id=args.image_id, expected_fingerprint=args.selection_fingerprint, action=args.action)
    except Exception as error:
        # Scalar modes must not accidentally feed an error JSON into a shell
        # variable. Fail with no stdout; no private data/exception messages.
        import sys
        print(json.dumps({'status': 'release_selection_blocked', 'failure_category': type(error).__name__}), file=sys.stderr)
        return 1
    print(value if isinstance(value, str) else json.dumps(value, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
