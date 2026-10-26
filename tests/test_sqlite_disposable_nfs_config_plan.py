import os
import pytest
from app import sqlite_disposable_nfs_config_plan as plan


def lab(tmp_path):
    (tmp_path/'.disposable_host_config').write_bytes(plan.MARKER)
    (tmp_path/'share.cfg').write_bytes(b'shareNFSEnabled="yes"\nother=original\n')
    return tmp_path


def test_candidates_preserve_source_and_are_exclusive(tmp_path):
    root=lab(tmp_path);before=(root/'share.cfg').read_bytes()
    result=plan.prepare_disposable_nfs_config_plan(root)
    assert (root/'share.cfg').read_bytes()==before
    assert (root/'nfs-plan/before.cfg').read_bytes()==before
    assert b'shareNFSEnabled="no"' in (root/'nfs-plan/disabled-candidate.cfg').read_bytes()
    assert result['apply_authorized'] is False and result['restoration_authorized'] is False
    with pytest.raises(FileExistsError):plan.prepare_disposable_nfs_config_plan(root)
    assert (root/'share.cfg').read_bytes()==before


@pytest.mark.parametrize('kind',['symlink','hardlink','fifo'])
def test_unsafe_source_is_not_read(kind,tmp_path):
    root=lab(tmp_path)
    (root/'share.cfg').rename(root/'original')
    if kind=='symlink':(root/'share.cfg').symlink_to(root/'original')
    elif kind=='hardlink':os.link(root/'original',root/'share.cfg')
    else:os.mkfifo(root/'share.cfg')
    with pytest.raises((RuntimeError,OSError)):plan.prepare_disposable_nfs_config_plan(root)
    assert not (root/'nfs-plan').exists()


def test_source_change_during_artifact_write_leaves_no_success(tmp_path,monkeypatch):
    root=lab(tmp_path);original=plan._write
    def change(*args):
        original(*args)
        if args[1]=='manifest.json':(root/'share.cfg').write_bytes(b'shareNFSEnabled=no\nother=external\n')
    monkeypatch.setattr(plan,'_write',change)
    with pytest.raises(RuntimeError,match='binding changed'):plan.prepare_disposable_nfs_config_plan(root)
    assert (root/'nfs-plan/before.cfg').read_bytes().endswith(b'other=original\n')
    assert (root/'share.cfg').read_bytes().endswith(b'other=external\n')


@pytest.mark.parametrize('drift',['directory','before','candidate'])
def test_replaced_plan_or_artifact_never_reports_success(tmp_path,monkeypatch,drift):
    root=lab(tmp_path);original=plan._write
    def change(*args):
        original(*args)
        if args[1]=='manifest.json':
            if drift=='directory':
                (root/'nfs-plan').rename(root/'retained-plan')
                (root/'nfs-plan').mkdir()
            else:
                name='before.cfg' if drift=='before' else 'disabled-candidate.cfg'
                (root/'nfs-plan'/name).write_bytes(b'shareNFSEnabled=no\nother=external\n')
    monkeypatch.setattr(plan,'_write',change)
    with pytest.raises(RuntimeError,match='plan binding/content changed'):
        plan.prepare_disposable_nfs_config_plan(root)
    assert (root/'share.cfg').read_bytes().endswith(b'other=original\n')
