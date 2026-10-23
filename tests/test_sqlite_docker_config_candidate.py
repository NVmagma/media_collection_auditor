import os

import pytest

from app.sqlite_disposable_nfs_config_plan import MARKER
from app import sqlite_docker_config_candidate as docker
from app import sqlite_disposable_nfs_config_plan as artifacts


@pytest.mark.parametrize('line',[b'DOCKER_ENABLED=yes',b'DOCKER_ENABLED="yes"',
                                b'DOCKER_ENABLED=no',b'DOCKER_ENABLED="no"'])
@pytest.mark.parametrize('ending',[b'',b'\n',b'\r\n'])
def test_exact_candidate_and_restoration(line,ending):
    original=b'# retained\nDOCKER_OPTS="unchanged"\n'+line+ending
    disabled=docker.disabled_docker_candidate(original)
    assert disabled==original.replace(b'=yes',b'=no').replace(b'="yes"',b'="no"')
    assert docker.reviewed_docker_restore_candidate(original=original,disabled=disabled,
                                                    current=disabled)==original


@pytest.mark.parametrize('content',[b'',b'other=yes\n',b'DOCKER_ENABLED=yes\nDOCKER_ENABLED=no\n',
    b'DOCKER_ENABLED=$(command)\n',b'export DOCKER_ENABLED=yes\n',b' DOCKER_ENABLED=yes\n',
    b'DOCKER_ENABLED="yes" # comment\n',b'DOCKER_ENABLED=maybe\n',b'DOCKER_ENABLED=yes\0'])
def test_unknown_preference_denies(content):
    with pytest.raises((ValueError,UnicodeError)):
        docker.disabled_docker_candidate(content)


def test_restore_never_overwrites_unrelated_edits():
    original=b'DOCKER_ENABLED="yes"\nother=original\n'
    disabled=docker.disabled_docker_candidate(original)
    with pytest.raises(RuntimeError,match='refuse restoration'):
        docker.reviewed_docker_restore_candidate(original=original,disabled=disabled,
            current=disabled.replace(b'original',b'changed'))


def lab(root):
    root=root.resolve()
    (root/'.disposable_host_config').write_bytes(MARKER)
    (root/'docker.cfg').write_bytes(b'DOCKER_ENABLED="yes"\nother=original\n')
    return root


def test_review_artifacts_preserve_source_and_refuse_reuse(tmp_path):
    root=lab(tmp_path);before=(root/'docker.cfg').read_bytes()
    result=docker.prepare_disposable_docker_config_plan(root)
    assert result['source_unchanged'] is True
    assert result['apply_authorized'] is False
    assert result['restoration_authorized'] is False
    assert (root/'docker.cfg').read_bytes()==before
    assert (root/'docker-plan/before.cfg').read_bytes()==before
    assert (root/'docker-plan/disabled-candidate.cfg').read_bytes()==docker.disabled_docker_candidate(before)
    with pytest.raises(FileExistsError):docker.prepare_disposable_docker_config_plan(root)


@pytest.mark.parametrize('kind',['symlink','hardlink','fifo'])
def test_unsafe_configuration_blocks(kind,tmp_path):
    root=lab(tmp_path)
    (root/'docker.cfg').rename(root/'retained')
    if kind=='symlink':(root/'docker.cfg').symlink_to(root/'retained')
    elif kind=='hardlink':os.link(root/'retained',root/'docker.cfg')
    else:os.mkfifo(root/'docker.cfg')
    with pytest.raises((RuntimeError,OSError)):docker.prepare_disposable_docker_config_plan(root)
    assert not (root/'docker-plan').exists()


def test_configuration_drift_retains_artifacts_without_success(tmp_path,monkeypatch):
    root=lab(tmp_path);write=artifacts._write
    def drift(*args):
        write(*args)
        if args[1]=='manifest.json':(root/'docker.cfg').write_bytes(b'DOCKER_ENABLED=no\nother=external\n')
    monkeypatch.setattr(artifacts,'_write',drift)
    with pytest.raises(RuntimeError,match='source binding changed'):
        docker.prepare_disposable_docker_config_plan(root)
    assert (root/'docker-plan/before.cfg').read_bytes().endswith(b'other=original\n')
    assert (root/'docker.cfg').read_bytes().endswith(b'other=external\n')
