import json
from unittest.mock import Mock
import pytest
from scripts import sqlite_candidate_image_lab as module

IMAGE = 'sha256:' + 'a' * 64
REVISION = 'b' * 40
CONTAINER = 'c' * 64


def metadata(**overrides):
    config = {'StopSignal': 'SIGINT', 'Entrypoint': ['python', '-m', 'app.main'], 'Volumes': None,
        'Labels': {'org.opencontainers.image.revision': REVISION,
                   'io.media-collection-auditor.sqlite-activation': 'disabled'}}
    config.update(overrides)
    return json.dumps([{'Id': IMAGE, 'Config': config}]).encode()


@pytest.mark.parametrize('image', ['candidate:latest', 'short', None])
def test_mutable_or_missing_image_never_reaches_docker(image, monkeypatch):
    command = Mock(); monkeypatch.setattr(module, 'command', command)
    with pytest.raises(ValueError): module.run(image=image, source_revision=REVISION, checkout='.')
    command.assert_not_called()


def test_unexpected_volume_or_entrypoint_refuses_before_container_creation(monkeypatch):
    command = Mock(return_value=metadata(Volumes={'/data': {}}))
    monkeypatch.setattr(module, 'command', command)
    with pytest.raises(RuntimeError): module.run(image=IMAGE, source_revision=REVISION, checkout='.')
    assert command.call_count == 1


@pytest.mark.parametrize('fail', [False, True])
def test_only_new_isolated_container_is_controlled_and_always_removed(monkeypatch, fail):
    calls = []
    def command(*args, **kwargs):
        calls.append(args)
        if args[:3] == ('docker', 'image', 'inspect'): return metadata()
        if args[0] == 'git': return b'committed-fixtures-only'
        if args[:2] == ('docker', 'create'):
            assert '--network' in args and args[args.index('--network') + 1] == 'none'
            assert '--read-only' in args and '--mount' not in args and '--publish' not in args
            assert '--cap-drop' in args and 'ALL' in args
            return CONTAINER.encode()
        if args[:2] == ('docker', 'exec'):
            if fail: raise RuntimeError('fixture failed')
            return b''
        if args[:2] == ('docker', 'inspect'):
            return json.dumps({'Running': False, 'OOMKilled': False, 'ExitCode': 143}).encode()
        return b''
    monkeypatch.setattr(module, 'command', command)
    if fail:
        with pytest.raises(RuntimeError): module.run(image=IMAGE, source_revision=REVISION, checkout='.')
    else:
        report = module.run(image=IMAGE, source_revision=REVISION, checkout='.')
        assert report['status'] == 'candidate_image_acceptance_complete'
        assert report['host_mounts'] is False and report['registry_push_performed'] is False
    assert calls[-1] == ('docker', 'rm', '--force', CONTAINER)
