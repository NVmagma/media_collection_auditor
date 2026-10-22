"""Exercise the exact probe child with inert commands; never create namespaces."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


PROBE = Path(__file__).resolve().parents[1] / "scripts/sqlite_nfs_namespace_probe.sh"


def run_child(tmp_path, *, net="net:[2]", mount="mnt:[2]", threads="0"):
    body = PROBE.read_text().split("<<'CHILD' || probe_status=$?\n", 1)[1].split("\nCHILD", 1)[0]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.jsonl"
    stub = '''
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ['PROBE_LOG'], 'a') as output:
    output.write(json.dumps([name, *sys.argv[1:]]) + '\\n')
if name == 'readlink':
    print(os.environ['PROBE_NET'] if sys.argv[1].endswith('/net') else os.environ['PROBE_MNT'])
elif name == 'cat':
    print(os.environ['PROBE_THREADS'])
'''
    for name in ("mount", "umount", "readlink", "cat"):
        path = bin_dir / name
        path.write_text("#!" + sys.executable + "\n" + stub)
        path.chmod(0o700)
    result = subprocess.run(["bash", "-eu", "-s", "--", "/fixture", "net:[1]", "mnt:[1]"],
                            input=body, text=True, capture_output=True, timeout=10,
                            env={**os.environ, "PATH": str(bin_dir) + os.pathsep + os.defpath,
                                 "PROBE_LOG": str(log), "PROBE_NET": net,
                                 "PROBE_MNT": mount, "PROBE_THREADS": threads})
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return result, calls


@pytest.mark.parametrize("identities", [{"net": "net:[1]"}, {"mount": "mnt:[1]"}])
def test_same_namespace_refused_before_mount(tmp_path, identities):
    result, calls = run_child(tmp_path, **identities)
    assert result.returncode == 2
    assert not any(call[0] in {"mount", "umount", "cat"} for call in calls)


def test_only_new_read_only_control_mount_is_observed(tmp_path):
    result, calls = run_child(tmp_path)
    assert result.returncode == 0, result.stderr
    assert [call for call in calls if call[0] == "mount"] == [
        ["mount", "-t", "nfsd", "-o", "ro,nosuid,nodev,noexec", "nfsd", "/fixture"]]
    assert [call for call in calls if call[0] == "cat"] == [["cat", "/fixture/threads"]]
    assert calls[-1] == ["umount", "--", "/fixture"]


def test_unexpected_threads_fail_and_unmount_only_private_view(tmp_path):
    result, calls = run_child(tmp_path, threads="8")
    assert result.returncode == 2
    assert "unexpected_isolated_threads" in result.stderr
    assert calls[-1] == ["umount", "--", "/fixture"]
