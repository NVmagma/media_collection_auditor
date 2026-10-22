"""Early isolation failures must stop before any privileged lab setup."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


LAB = Path(__file__).resolve().parents[1] / "scripts/sqlite_nfs_client_lab.sh"


@pytest.mark.parametrize("net, mnt", [("host-net", "private-mnt"),
                                     ("wrong-net", "private-mnt"),
                                     ("client-net", "host-mnt")])
def test_namespace_mismatch_prevents_privileged_setup(tmp_path, net, mnt):
    body = LAB.read_text().split("<<'SERVER' || server_status=$?\n", 1)[1].split("\nSERVER", 1)[0]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.jsonl"
    stub = '''
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ['LAB_LOG'], 'a') as output:
    output.write(json.dumps([name, *sys.argv[1:]]) + '\\n')
if name == 'readlink':
    print(os.environ['LAB_NET'] if sys.argv[1].endswith('/net') else os.environ['LAB_MNT'])
else:
    sys.exit(77)
'''
    for name in ("readlink", "mount"):
        path = bin_dir / name
        path.write_text("#!" + sys.executable + "\n" + stub)
        path.chmod(0o700)
    result = subprocess.run(["bash", "-euo", "pipefail", "-s", "--", str(tmp_path),
                             "host-net", "host-mnt", "host-control", "client-net"],
                            input=body, text=True, capture_output=True, timeout=10,
                            env={**os.environ, "PATH": str(bin_dir) + os.pathsep + os.defpath,
                                 "LAB_LOG": str(log), "LAB_NET": net, "LAB_MNT": mnt})
    assert result.returncode != 0
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert all(call[0] == "readlink" for call in calls)
