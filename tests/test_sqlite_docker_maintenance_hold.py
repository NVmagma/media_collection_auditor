"""Real files, locks and child death; no Docker or production service access."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from app.sqlite_docker_maintenance_hold import create_disposable_hold, held_disposable_hold, HOLD


def fixture(tmp_path):
    root = tmp_path / 'control'
    root.mkdir()
    (root / '.disposable_authorization').write_bytes(b'DISPOSABLE ONLY\n')
    create_disposable_hold(root)
    return root


def snapshot(root):
    return {p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}


def test_existing_hold_is_never_overwritten_or_released(tmp_path):
    root=fixture(tmp_path)
    before=snapshot(root)
    with pytest.raises(FileExistsError): create_disposable_hold(root)
    with held_disposable_hold(root) as verify:
        verify()
        with pytest.raises(RuntimeError,match='active'):
            with held_disposable_hold(root): pytest.fail('Second listener must not adopt')
    assert snapshot(root)==before


@pytest.mark.parametrize('change', ['missing','malformed','released','symlink','hardlink','fifo'])
def test_unknown_hold_fails_closed_without_repair(tmp_path,change):
    root=fixture(tmp_path)
    path=root/'maintenance.hold'
    path.unlink()
    if change=='malformed': path.write_bytes(b'partial')
    elif change=='released': path.write_bytes(b'{"phase":"released"}\n')
    elif change=='symlink': path.symlink_to(root/'.disposable_authorization')
    elif change=='hardlink': os.link(root/'.disposable_authorization',path)
    elif change=='fifo': os.mkfifo(path)
    with pytest.raises((OSError,RuntimeError)):
        with held_disposable_hold(root): pytest.fail('Unsafe state cannot bind')
    if change == 'missing':
        assert not path.exists()
    else:
        assert os.path.lexists(path)


@pytest.mark.parametrize('change',['hold','lock','root'])
def test_live_binding_loss_never_becomes_a_fresh_hold(tmp_path,change):
    root=fixture(tmp_path)
    with pytest.raises(RuntimeError):
        with held_disposable_hold(root) as verify:
            if change=='root':
                root.rename(tmp_path/'retained')
                root.mkdir()
            else:
                path=root/('maintenance.hold' if change=='hold' else 'authorization.lock')
                path.rename(root/'retained')
                path.write_bytes(HOLD if change=='hold' else b'')
            verify()


def test_committed_hold_survives_process_exit_without_cleanup(tmp_path):
    root=tmp_path/'child'
    result=subprocess.run([sys.executable,'-B','-c',
        'import os,sys; from pathlib import Path; '
        'from app.sqlite_docker_maintenance_hold import create_disposable_hold,held_disposable_hold; '
        'r=Path(sys.argv[1]); r.mkdir(); (r/".disposable_authorization").write_bytes(b"DISPOSABLE ONLY\\n"); '
        'create_disposable_hold(r); c=held_disposable_hold(r); c.__enter__(); os._exit(23)',str(root)],
        capture_output=True,timeout=10)
    assert result.returncode==23,result.stderr.decode(errors='replace')
    before=snapshot(root)
    with held_disposable_hold(root) as verify: verify()
    assert snapshot(root)==before
