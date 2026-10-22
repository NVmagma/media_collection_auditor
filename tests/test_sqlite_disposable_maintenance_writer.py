import os
from pathlib import Path
import select
import subprocess
import sys

import pytest

from app import sqlite_disposable_maintenance_controller as controller
from app.sqlite_disposable_maintenance_journal import (
    NEXT, advance_disposable_journal as advance, create_disposable_journal as create,
    inspect_disposable_journal as inspect,
)
from app.sqlite_disposable_maintenance_writer import open_disposable_writer as open_writer


@pytest.mark.parametrize("phase", list(NEXT.values())[:-1])
def test_old_handle_and_new_writer_denied_at_every_pending_phase(tmp_path, phase):
    root = tmp_path / "lab"
    create(root)
    with open_writer(root) as writer:
        writer.write(b"before\n")
        for revision, next_phase in enumerate(NEXT.values()):
            advance(root, expected_revision=revision, phase=next_phase)
            if next_phase == phase:
                break
        before = (root / "writer.fixture").read_bytes()
        with pytest.raises(RuntimeError, match="fenced"):
            writer.write(b"unexpected\n")
        with pytest.raises(RuntimeError, match="fenced"):
            with open_writer(root):
                pytest.fail("Pending maintenance allowed a new writer")
        assert (root / "writer.fixture").read_bytes() == before


def test_only_explicit_completed_release_reopens_writer(tmp_path):
    root = tmp_path / "lab"
    create(root)
    with open_writer(root) as writer:
        writer.write(b"before\n")
        controller.fence_disposable_fixture(root, expected_revision=0)
        advance(root, expected_revision=2, phase="work_pending")
        advance(root, expected_revision=3, phase="outcomes_verified")
        with pytest.raises(RuntimeError, match="fenced"):
            writer.write(b"too early\n")
        controller.release_disposable_fixture(root, expected_revision=4)
        writer.write(b"after\n")
    assert (root / "writer.fixture").read_bytes() == b"before\nafter\n"
    assert inspect(root)["external_writer_exclusion_verified"] is False


def test_live_process_with_old_descriptor_cannot_write_after_fence(tmp_path):
    root = tmp_path / "lab"
    create(root)
    code = '''
import sys
from app.sqlite_disposable_maintenance_writer import open_disposable_writer
with open_disposable_writer(sys.argv[1]) as writer:
    writer.write(b"before\\n")
    print("READY", flush=True)
    sys.stdin.readline()
    try:
        writer.write(b"unexpected\\n")
    except RuntimeError:
        print("BLOCKED", flush=True)
    else:
        raise RuntimeError("Writer bypassed maintenance")
'''
    child = subprocess.Popen([sys.executable, "-B", "-c", code, str(root)],
                             cwd=Path(__file__).resolve().parents[1],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        assert select.select([child.stdout], [], [], 15)[0], "Writer did not become ready"
        assert child.stdout.readline().strip() == "READY"
        controller.fence_disposable_fixture(root, expected_revision=0)
        output, errors = child.communicate("write\n", timeout=15)
        assert child.returncode == 0, errors
        assert output.strip() == "BLOCKED"
        assert (root / "writer.fixture").read_bytes() == b"before\n"
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=15)


def test_controller_death_does_not_reopen_cooperative_writer(tmp_path):
    root = tmp_path / "lab"
    create(root)
    code = '''
import os, sys
from app import sqlite_disposable_maintenance_controller as c
original = c._receipt
def die(root, action):
    original(root, action)
    os._exit(24)
c._receipt = die
c.fence_disposable_fixture(sys.argv[1], expected_revision=0)
'''
    result = subprocess.run([sys.executable, "-B", "-c", code, str(root)],
                            cwd=Path(__file__).resolve().parents[1], timeout=15)
    assert result.returncode == 24
    with pytest.raises(RuntimeError, match="fenced"):
        with open_writer(root):
            pytest.fail("Controller death reopened writes")
    assert inspect(root)["phase"] == "fence_requested"
    assert not (root / "writer.fixture").exists()


def test_replaced_writer_file_does_not_receive_old_handle_writes(tmp_path):
    root = tmp_path / "lab"
    create(root)
    with open_writer(root) as writer:
        writer.write(b"before")
        (root / "writer.fixture").rename(root / "retained.fixture")
        (root / "writer.fixture").write_bytes(b"replacement")
        with pytest.raises(RuntimeError, match="binding"):
            writer.write(b"unexpected")
    assert (root / "retained.fixture").read_bytes() == b"before"
    assert (root / "writer.fixture").read_bytes() == b"replacement"
