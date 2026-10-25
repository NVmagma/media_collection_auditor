"""Actual cached rollback image: synthetic JSON roundtrip only, network forbidden."""
import json
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys


def verify():
    import requests
    def forbid(*args, **kwargs): raise RuntimeError('Fixture network forbidden')
    requests.sessions.Session.request = forbid
    root = Path('/tmp/rollback-fixture'); root.mkdir(mode=0o700)
    state = {section: {} for section in ('first_seen', 'queued', 'in_removal', 'keep_seen', 'arr_sync_pending')}
    state['first_seen']['Fixture Movie'] = '2024-01-01T00:00:00'
    state['queued']['Fixture Holding'] = '2024-02-01T00:00:00'
    state['keep_seen']['TV/Fixture Show'] = '2024-03-01T00:00:00'
    state['arr_sync_pending']['Fixture Holding'] = {'stage': 'holding', 'root': '/synthetic/holding',
        'service': 'radarr', 'title_id': 17, 'monitored': False, 'unknown_retry': {'attempts': 1}}
    state['unknown_extension'] = {'newest': ['caf\u00e9', False, None]}
    path = root / 'state.json'
    path.write_text(json.dumps(state, ensure_ascii=True))
    os.environ.update(STATE_FILE=str(path), DRY_RUN='true', ALLOW_PERMANENT_DELETE='false',
        ALLOW_FILESYSTEM_DELETE='false', ALLOW_CROSS_FILESYSTEM_MOVES='false')
    import collection_auditor as auditor
    if auditor.load_state() != state: raise RuntimeError('Rollback loader parity failed')
    auditor.save_state(state)
    if auditor.load_state() != state or json.loads(path.read_bytes()) != state:
        raise RuntimeError('Rollback save/reload parity failed')
    return {'status': 'original_image_json_roundtrip_verified', 'fixture_only': True,
        'network_collection_performed': False, 'production_state_read': False,
        'service_actions_performed': False}


if __name__ == '__main__':
    try:
        with redirect_stdout(io.StringIO()):
            report = verify()
        print(json.dumps(report))
    except Exception as error:
        print(json.dumps({'status': 'original_image_json_roundtrip_failed',
            'failure_category': type(error).__name__, 'fixture_only': True}))
        raise SystemExit(1)
