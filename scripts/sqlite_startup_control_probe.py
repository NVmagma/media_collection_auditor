"""Read selected Unraid startup evidence; never execute or source host helpers."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

LIMIT = 1024 * 1024


def read_regular(path):
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK), 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return None
            data = stream.read(LIMIT + 1)
        return data if len(data) <= LIMIT else None
    except OSError:
        return None


def preference(data, key):
    if data is None:
        return 'unavailable'
    lines = [line for line in data.splitlines()
             if re.match(rb'\s*' + key.encode() + rb'\s*=', line)]
    if len(lines) != 1:
        return 'unverified'
    match = re.fullmatch(key.encode() + rb'="(yes|no)"', lines[0])
    return match[1].decode() if match else 'unverified'


def observe(root=Path('/')):
    def read(name):
        return read_regular(root / name.lstrip('/'))
    sources = {}
    for name in ('/etc/rc.d/rc.docker', '/usr/local/etc/rc.d/rc.docker',
                 '/etc/rc.d/rc.local', '/boot/config/go'):
        data = read(name)
        sources[name] = {'status': 'observed', 'sha256': hashlib.sha256(data).hexdigest()} if data is not None else {'status': 'unavailable'}
    settings = {}
    for name, key in (('/boot/config/docker.cfg', 'DOCKER_ENABLED'),
                      ('/boot/config/share.cfg', 'shareNFSEnabled')):
        settings[name] = {key: preference(read(name), key)}
    data = read('/var/lib/docker/unraid-autostart')
    entries = []
    valid = data is not None
    if data is not None:
        for line in data.splitlines():
            if not line.strip():
                continue
            match = re.fullmatch(rb'([a-zA-Z0-9][a-zA-Z0-9_.-]*)(?:[ \t]+([0-9]+))?[ \t]*', line)
            if not match:
                valid = False
                break
            entries.append({'container': match[1].decode(),
                            'delay_seconds': int(match[2]) if match[2] else None})
    return {'read_only': True, 'production_activation': 'disabled',
            'production_authorized': False, 'writer_exclusion_verified': False,
            'restart_inhibition_verified': False, 'automatic_action': 'none',
            'status': 'review_required', 'settings': settings, 'source_identities': sources,
            'unraid_autostart': {'status': 'observed' if valid else 'unverified',
                                 'entries': entries if valid else []},
            'limitations': ['snapshot_never_authorizes_enforcement',
                            'custom_jobs_and_privileged_bypasses_unverified',
                            'boot_order_and_restart_fence_unverified']}


if __name__ == '__main__':
    print(json.dumps(observe(), indent=2, sort_keys=True))
