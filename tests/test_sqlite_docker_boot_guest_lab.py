from pathlib import Path
import pytest
from scripts import sqlite_docker_boot_guest_lab as boot


def test_unit_ordering_keeps_engine_bound_to_deny_policy(tmp_path):
    rendered = boot.units(tmp_path/'lab', tmp_path/'source', tmp_path/'bin')
    engine = rendered[boot.PREFIX+'-engine.service']
    assert f'BindsTo={boot.PREFIX}-policy.service\nAfter={boot.PREFIX}-policy.service' in engine
    assert 'ExecStartPre=' in engine and '--phase wait' in engine
    assert 'Restart=no' in engine
    assert '--resume-fixture' in rendered[boot.PREFIX+'-policy.service']
    assert 'WantedBy=multi-user.target' in engine


@pytest.mark.parametrize('path', ['relative', '/tmp/space here', '/tmp/%n', '/tmp/a\nb', '/tmp/../etc'])
def test_unsafe_unit_paths_rejected(path):
    with pytest.raises(ValueError):
        boot.safe_path(path)


def test_wrong_host_prepare_never_reads_or_controls_services(monkeypatch):
    monkeypatch.setattr(boot, 'require_guest', lambda: (_ for _ in ()).throw(RuntimeError('wrong host')))
    monkeypatch.setattr(Path, 'read_bytes', lambda *a: pytest.fail('No state reads'))
    monkeypatch.setattr(boot.subprocess, 'run', lambda *a, **k: pytest.fail('No service controls'))
    with pytest.raises(RuntimeError, match='wrong host'):
        boot.prepare('/tmp/lab', '/tmp/source', '/tmp/bin')


def test_same_boot_is_not_accepted_as_reboot(monkeypatch, tmp_path):
    import json
    monkeypatch.setattr(boot, 'require_guest', lambda: None)
    root = tmp_path/'lab'
    root.mkdir()
    (root/'boot-manifest.json').write_text(json.dumps({'boot_id': 'same'}))
    original = Path.read_text
    def text(path, *a, **k):
        if str(path) == '/proc/sys/kernel/random/boot_id':
            return 'same\n'
        return original(path, *a, **k)
    monkeypatch.setattr(Path, 'read_text', text)
    monkeypatch.setattr(boot.subprocess, 'run', lambda *a, **k: pytest.fail('No service check'))
    monkeypatch.setattr(boot, 'api', lambda *a, **k: pytest.fail('No Docker call'))
    with pytest.raises(RuntimeError, match='reboot required'):
        boot.check(root)


def test_policy_wait_does_not_accept_deny_response(monkeypatch, tmp_path):
    times = iter([0, 0, 21])
    monkeypatch.setattr(boot.time, 'monotonic', lambda: next(times))
    monkeypatch.setattr(boot.time, 'sleep', lambda *a: None)
    monkeypatch.setattr(boot, 'api', lambda *a: (200, b'{"Allow":false}'))
    with pytest.raises(RuntimeError, match='must not start'):
        boot.wait_policy(tmp_path)


def test_policy_wait_accepts_only_explicit_authz_activation(monkeypatch, tmp_path):
    monkeypatch.setattr(boot, 'api', lambda *a: (200, b'{"Implements":["authz"]}'))
    assert boot.wait_policy(tmp_path) is None
