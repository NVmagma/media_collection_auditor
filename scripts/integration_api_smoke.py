#!/usr/bin/env python3
"""Synthetic Flask client smoke test; no listener, network or real state reads."""
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'app'), str(root)]
    with tempfile.TemporaryDirectory(prefix='integration-api-fixture-') as directory:
        state = Path(directory) / 'state.json'
        raw = '{"queued":{"fixture-title":"2024-01-01"}}'
        state.write_text(raw)
        os.environ['STATE_FILE'] = str(state)
        os.environ['WEB_SESSION_SECRET'] = secrets.token_urlsafe(32)
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
        response = client.get('/api/v1/summary', headers=headers)
        assert response.status_code == 200
        assert response.json['tracking_counts']['holding'] == 1
        assert response.json['production_authorized'] is False
        assert response.json['freshness_verified'] is False
        assert 'fixture-title' not in response.text
        assert response.headers['Cache-Control'] == 'no-store'
        assert client.post('/api/run-now', headers=headers).status_code == 401
        assert client.post('/api/rescue', headers=headers).status_code == 401
        assert state.read_text() == raw
        state.unlink()
        assert client.get('/api/v1/summary', headers=headers).status_code == 503
    print(json.dumps({'status': 'disposable_api_smoke_passed', 'fixture_only': True,
                      'production_authorized': False, 'production_activation': 'disabled',
                      'network_collection_performed': False}))


if __name__ == '__main__':
    main()
