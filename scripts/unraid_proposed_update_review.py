"""Run inside the cached candidate image with current mounts forced read-only.

Only the packaged candidate activation validator is used, never the checkout's
profile. Private inspect/settings/binding payloads and exceptions are not printed.
"""
import json
import os
from pathlib import Path
import stat
import sys

from scripts.unraid_update_plan import proposed_update

LIMIT = 16 * 1024 * 1024


def read_binding(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('regular_binding_required')
        raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('bounded_binding_required')
        return raw, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def main():
    try:
        from app.sqlite_json import parse_unique_json
        from app.sqlite_release_profile import PROFILE, SOURCE_REVISION
        from app.sqlite_preview_activation import validate_preview_activation
        raw = sys.stdin.buffer.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('bounded_input_required')
        payload = parse_unique_json(raw)
        containers, images = payload['containers'], payload['images']
        if len(containers) != 1 or len(images) != 1:
            raise ValueError('single_candidate_and_container_required')
        container, image = containers[0], images[0]
        settings = dict(value.split('=', 1) for value in container['Config']['Env'])
        database = Path(settings.get('SQLITE_STATE_FILE', '/sqlite-control/release/state.db'))
        if not database.is_absolute():
            raise ValueError('absolute_state_path_required')
        binding_path = database.parent / 'preview-release.json'
        before, identity = read_binding(binding_path)
        revision = parse_unique_json(before).get('source_revision')
        outcome = 'invalid'
        # Even a same-revision image must pass the full candidate validator.
        # A changed revision requires explicit preparation; it is never rebound here.
        if revision == SOURCE_REVISION:
            try:
                validate_preview_activation(settings=settings)
                outcome = 'valid'
            except Exception:
                pass
        if read_binding(binding_path) != (before, identity):
            outcome = 'changed'
        report = proposed_update(container=container, image=image, packaged_profile=PROFILE,
            packaged_revision=SOURCE_REVISION, binding_revision=revision, binding_validation=outcome)
    except Exception:
        report = {'status': 'review_required', 'read_only': True, 'automatic_action': 'none',
                  'update_authorized': False, 'media_actions_authorized': False,
                  'candidate_binding_verified': False, 'blockers': ['candidate_binding_inputs_unavailable']}
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] == 'candidate_matches_existing_binding' else 2


if __name__ == '__main__':
    raise SystemExit(main())
