"""Inspect private inputs without outputting values, modifying files or Docker."""
import argparse
import json
import os
import stat
import sys
from app.unraid_update_review import LIMIT, review_update


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--templates', required=True)
    args = parser.parse_args()
    stage = 'template_directory_open'
    try:
        folder = os.open(args.templates, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            stage = 'template_file_reads'
            templates = []
            for name in sorted(os.listdir(folder)):
                if not name.endswith('.xml'):
                    continue
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
                with os.fdopen(fd, 'rb') as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise ValueError('regular_file_required')
                    templates.append((name, stream.read(LIMIT + 1)))
            stage = 'container_inspect_input'
            raw = sys.stdin.buffer.read(8 * LIMIT + 1)
            if len(raw) > 8 * LIMIT:
                raise ValueError('bounded_inspect_required')
            items = json.loads(raw)
            if not isinstance(items, list) or len(items) != 1:
                raise ValueError('single_container_required')
            report = review_update(templates=templates, container=items[0])
        finally:
            os.close(folder)
    except (OSError, ValueError, TypeError):
        report = {'status': 'review_required', 'read_only': True, 'automatic_action': 'none',
                  'update_authorized': False, 'binding_verified': False,
                  'blockers': ['inventory_unreadable_or_unsupported'], 'diagnostic_stage': stage}
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] == 'template_matches_observed_container' else 2


if __name__ == '__main__':
    raise SystemExit(main())
