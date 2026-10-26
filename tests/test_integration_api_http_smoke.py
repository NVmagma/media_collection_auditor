"""Real HTTP fixture plus deterministic cleanup when startup evidence fails."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
from scripts import integration_api_http_smoke as module

ROOT = Path(__file__).resolve().parents[1]


def test_real_http_contract_in_disposable_child(tmp_path):
    result = subprocess.run([sys.executable, '-B', str(
        ROOT / 'scripts/integration_api_http_smoke.py')], cwd=tmp_path,
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report['status'] == 'disposable_api_http_smoke_passed'
    assert report['server_process_stopped'] is True
    assert report['widget_rendering_verified'] is False
    assert report['production_authorized'] is False
    assert 'private-fixture-title' not in result.stdout


@pytest.mark.parametrize('signal', ['timeout', 'unavailable', 'invalid_port'])
def test_startup_uncertainty_stops_only_created_child(monkeypatch, signal):
    events = []

    class Pipe:
        def poll(self, timeout):
            assert timeout == 10
            return signal != 'timeout'
        def recv(self):
            return {'status': 'unavailable'} if signal == 'unavailable' else {'status': 'ready', 'port': True}
        def close(self):
            pass

    class Process:
        alive = True
        def start(self):
            events.append('start')
        def is_alive(self):
            return self.alive
        def terminate(self):
            events.append('terminate')
            self.alive = False
        def join(self, timeout):
            assert timeout == 3
            events.append('join')
        def close(self):
            events.append('close')

    class Context:
        def Pipe(self, duplex):
            assert duplex is False
            return Pipe(), Pipe()
        def Process(self, **kwargs):
            assert kwargs['target'] == module._serve_fixture
            assert kwargs['daemon'] is True
            return Process()

    monkeypatch.setattr(module.multiprocessing, 'get_context', lambda mode: Context())
    monkeypatch.setattr(module, '_request', lambda *a, **kw: pytest.fail('No request without readiness'))
    with pytest.raises(module.FixtureFailure):
        module.run_fixture()
    assert events == ['start', 'terminate', 'join', 'close']


def test_http_fixture_rejects_external_target_arguments(tmp_path):
    result = subprocess.run([sys.executable, '-B', str(
        ROOT / 'scripts/integration_api_http_smoke.py'), '--url', 'https://production.invalid'],
        cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert json.loads(result.stdout)['reason'] == 'fixture_accepts_no_arguments'
    assert 'production.invalid' not in result.stdout
