"""Build an untagged, sealed candidate from committed Git bytes; never publish."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory


def build(*, checkout, base_image):
    if not isinstance(base_image, str) or not re.fullmatch(r'python@sha256:[0-9a-f]{64}', base_image):
        raise ValueError('Pinned official Python digest required')
    checkout = Path(checkout)
    def git(*args):
        return subprocess.run(['git', *args], cwd=checkout, capture_output=True,
                              check=True, timeout=30).stdout
    if git('branch', '--show-current').decode().strip() not in ('feature/sqlite', 'feature/unraid', 'feature/interface-api'):
        raise RuntimeError('Build requires an official or approved development branch')
    revision = git('rev-parse', '--verify', 'HEAD').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise RuntimeError('Exact source revision required')
    git('diff', '--exit-code', 'HEAD', '--', 'app', 'requirements.txt',
        'docker/sqlite-candidate.Dockerfile', 'docker/sqlite-candidate-constraints.txt', 'unraid/assets')
    archive = git('archive', '--format=tar', revision)
    with TemporaryDirectory(prefix='mca-candidate-build.') as temporary:
        iid = Path(temporary) / 'image-id'
        subprocess.run(['docker', 'build', '--pull=false', '--file', 'docker/sqlite-candidate.Dockerfile',
            '--build-arg', 'BASE_IMAGE=' + base_image, '--build-arg', 'SOURCE_REVISION=' + revision,
            '--iidfile', str(iid), '-'], cwd=checkout, input=archive, check=True, timeout=600, stdout=sys.stderr)
        image = iid.read_text().strip()
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise RuntimeError('Built image identity unavailable')
    return {'status': 'sealed_candidate_built', 'image_id': image, 'source_revision': revision,
        'base_image': base_image, 'registry_push_performed': False, 'production_authorized': False,
        'production_activation': 'disabled'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-image', required=True)
    args = parser.parse_args()
    print(json.dumps(build(checkout=Path(__file__).resolve().parents[1], base_image=args.base_image)))
