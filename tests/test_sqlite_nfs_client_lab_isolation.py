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
                                     ("client-net", "host-mnt"),
                                     ("client-net", "private-mnt")])
def test_missing_or_reused_isolation_prevents_privileged_setup(tmp_path, net, mnt):
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


def test_real_pause_worker_death_leaves_regular_fixture_control_stopped(tmp_path):
    # Exercise the actual shell worker with regular files, not kernel controls.
    source = LAB.read_text()
    function = "pause_controller(){\n" + source.split("pause_controller(){\n", 1)[1].split("\n}\nif", 1)[0] + "\n}\n"
    control = tmp_path / "control"
    control.mkdir()
    (control / "threads").write_text("1\n")
    fixture = '''
lab=$1
control=$1/control
scenario=controller-crash
verify(){ [ -f "$control/threads" ]; }
''' + function + '''
pause_controller &
worker=$!
for attempt in $(seq 1 100); do
  [ ! -f "$control/server.paused" ] || break
  sleep 0.01
done
[ -f "$control/server.paused" ]
[ "$(cat "$control/threads")" = 0 ]
kill -KILL "$worker"
status=0
wait "$worker" 2>/dev/null || status=$?
[ "$status" = 137 ]
[ "$(cat "$control/threads")" = 0 ]
'''
    result = subprocess.run(["bash", "-eu", "-s", "--", str(tmp_path)],
                            input=fixture, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert (control / "threads").read_text() == "0\n"
    assert not (control / "server.restored").exists()
