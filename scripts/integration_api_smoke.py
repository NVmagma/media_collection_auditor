#!/usr/bin/env python3
"""Synthetic Flask client smoke test; no listener, network or real state reads."""
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile


def main():
    read_only_service = sys.argv[1:] == ['--read-only-service']
    if sys.argv[1:] and not read_only_service:
        raise SystemExit(2)
    os.environ['READ_ONLY_API_SERVICE'] = 'true' if read_only_service else 'false'
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'app'), str(root)]
    with tempfile.TemporaryDirectory(prefix='integration-api-fixture-') as directory:
        state = Path(directory) / 'state.json'
        raw = '{"queued":{"fixture-title":"2024-01-01"}}'
        state.write_text(raw)
        os.environ['STATE_FILE'] = str(state)
        os.environ['AUDIT_HISTORY_FILE'] = str(Path(directory) / 'history.jsonl')
        os.environ['WEB_SESSION_SECRET'] = secrets.token_urlsafe(32)
        os.environ['WEB_SESSION_KEY_FILE'] = str(Path(directory) / 'must-not-create.key')
        os.environ.pop('INTEGRATION_API_TOKEN', None)
        import requests

        def deny_network(*args, **kwargs):
            raise AssertionError('Network collection forbidden in fixture')

        requests.sessions.Session.request = deny_network
        import web
        client = web.app.test_client()
        assert client.get('/api/v1/summary').status_code == 404
        token = secrets.token_urlsafe(32)
        os.environ['INTEGRATION_API_TOKEN'] = token
        headers = {'Authorization': 'Bearer ' + token}
        assert client.get('/api/v1/summary').status_code == 401
        assert client.get('/api/v1/audit-status').status_code == 401
        response = client.get('/api/v1/summary', headers=headers)
        assert response.status_code == 200
        assert response.json['tracking_counts']['holding'] == 1
        assert response.json['production_authorized'] is False
        assert response.json['freshness_verified'] is False
        assert 'fixture-title' not in response.text
        assert response.headers['Cache-Control'] == 'no-store'
        audit = client.get('/api/v1/audit-status', headers=headers)
        assert audit.status_code == (503 if read_only_service else 200)
        assert audit.json['running'] is (None if read_only_service else False)
        assert audit.json['freshness_verified'] is False
        assert audit.json['last_result'] is None
        assert client.post('/api/run-now', headers=headers).status_code == (404 if read_only_service else 401)
        assert client.post('/api/rescue', headers=headers).status_code == (404 if read_only_service else 401)
        if read_only_service:
            assert client.get('/login').status_code == 404
            assert 'collection_auditor' not in sys.modules
            assert not (Path(directory) / 'must-not-create.key').exists()
        os.environ.pop('INTEGRATION_API_TITLE_DETAILS', None)
        title_paths = ('/api/v1/titles/oldest-waiting', '/api/v1/titles/leaving-soon')
        for path in title_paths:
            assert client.get(path, headers=headers).status_code == 404
        os.environ['INTEGRATION_API_TITLE_DETAILS'] = 'true'
        # Never consult a deployment configuration during synthetic image checks.
        web.load_config = lambda: {'HOLDING_DAYS': '7'}
        for path in title_paths:
            assert client.get(path).status_code == 401
            titles = client.get(path, headers=headers)
            assert titles.status_code == 200
            assert titles.json['production_authorized'] is False
            assert titles.json['freshness_verified'] is False
            assert titles.headers['Cache-Control'] == 'no-store'
        holding = client.get(title_paths[1], headers=headers).json['items']
        assert len(holding) == 1
        assert holding[0]['title'] == 'fixture-title'
        assert holding[0]['estimated_removal_stage_at'] == '2024-01-08T00:00:00'
        assert holding[0]['transition_authorized'] is False
        assert client.get(title_paths[0], headers=headers).json['items'] == []
        assert state.read_text() == raw
        state.unlink()
        assert client.get('/api/v1/summary', headers=headers).status_code == 503
        for path in title_paths:
            unavailable = client.get(path, headers=headers)
            assert unavailable.status_code == 503
            assert unavailable.json['items'] is None
    print(json.dumps({'status': 'disposable_api_smoke_passed', 'fixture_only': True,
                      'production_authorized': False, 'production_activation': 'disabled',
                      'network_collection_performed': False,
                      'read_only_service': read_only_service}))


if __name__ == '__main__':
    main()
