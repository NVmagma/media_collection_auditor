import json

import pytest

from scripts import sqlite_scheduled_move_container_lab as lab


def test_private_fixture_has_no_host_access_and_is_removed_after_failure(monkeypatch):
    image = 'sha256:' + 'a' * 64; container = 'b' * 64; calls = []
    def command(*args, **kwargs):
        calls.append(args)
        if args[:3] == ('docker', 'image', 'inspect'):
            return json.dumps([{'Id': image, 'Config': {'Volumes': None}}]).encode()
        if args[:2] == ('docker', 'create'): return container.encode()
        if args[:2] == ('docker', 'start'): raise RuntimeError('fixture failure')
        return b''
    monkeypatch.setattr(lab, 'command', command)
    with pytest.raises(RuntimeError, match='fixture failure'): lab.run(image)
    create = next(args for args in calls if args[:2] == ('docker', 'create'))
    for flag in ('--mount', '--volume', '--privileged', '--cap-add', '--device'):
        assert flag not in create
    assert create[create.index('--network') + 1] == 'none'
    assert create[create.index('--cap-drop') + 1] == 'ALL'
    assert '--read-only' in create and '--pull=never' in create
    assert calls[-1] == ('docker', 'rm', '--force', container)


def test_image_tags_rejected_before_docker_contact(monkeypatch):
    monkeypatch.setattr(lab, 'command', lambda *a, **k: pytest.fail('Docker contacted'))
    with pytest.raises(ValueError): lab.run('python:latest')


def test_declared_image_volumes_refused(monkeypatch):
    image = 'sha256:' + 'a' * 64
    monkeypatch.setattr(lab, 'command', lambda *a, **k:
        json.dumps([{'Id': image, 'Config': {'Volumes': {'/media': {}}}}]).encode())
    with pytest.raises(RuntimeError, match='without declared volumes'): lab.run(image)
