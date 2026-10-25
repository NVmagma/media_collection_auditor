import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from scripts import sqlite_candidate_build as module

BASE = 'python@sha256:' + 'a' * 64
REVISION = 'b' * 40
IMAGE = 'sha256:' + 'c' * 64


@pytest.mark.parametrize('base', ['python:3.12-slim', 'other@sha256:' + 'a' * 64, None])
def test_only_pinned_official_base_can_reach_docker(base, monkeypatch):
    run = Mock(); monkeypatch.setattr(module.subprocess, 'run', run)
    with pytest.raises(ValueError): module.build(checkout='.', base_image=base)
    run.assert_not_called()


def test_build_uses_committed_archive_without_publishing_or_changing_tags(tmp_path, monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[:3] == ['git', 'branch', '--show-current']: return SimpleNamespace(stdout=b'feature/sqlite\n')
        if args[:3] == ['git', 'rev-parse', '--verify']: return SimpleNamespace(stdout=REVISION.encode())
        if args[:2] == ['git', 'diff']: return SimpleNamespace(stdout=b'')
        if args[:2] == ['git', 'archive']: return SimpleNamespace(stdout=b'exact-committed-archive')
        assert args[:2] == ['docker', 'build']
        Path(args[args.index('--iidfile') + 1]).write_text(IMAGE)
        assert kwargs['input'] == b'exact-committed-archive'
        assert '--tag' not in args and '--push' not in args
        assert 'docker/sqlite-candidate.Dockerfile' in args
        assert 'SOURCE_REVISION=' + REVISION in args and 'BASE_IMAGE=' + BASE in args
        return SimpleNamespace(stdout=b'')
    monkeypatch.setattr(module.subprocess, 'run', run)
    report = module.build(checkout=tmp_path, base_image=BASE)
    assert report['image_id'] == IMAGE and report['registry_push_performed'] is False
    assert calls[3][0] == ['git', 'archive', '--format=tar', REVISION]


def test_wrong_branch_never_builds(monkeypatch):
    run = Mock(return_value=SimpleNamespace(stdout=b'main\n'))
    monkeypatch.setattr(module.subprocess, 'run', run)
    with pytest.raises(RuntimeError): module.build(checkout='.', base_image=BASE)
    assert run.call_count == 1


def test_dirty_runtime_inputs_never_build(monkeypatch):
    run = Mock(side_effect=[SimpleNamespace(stdout=b'feature/sqlite\n'),
        SimpleNamespace(stdout=REVISION.encode()), subprocess.CalledProcessError(1, 'git diff')])
    monkeypatch.setattr(module.subprocess, 'run', run)
    with pytest.raises(subprocess.CalledProcessError): module.build(checkout='.', base_image=BASE)
    assert run.call_count == 3
