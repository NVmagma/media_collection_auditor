"""Run the actual lab child against inert commands and regular fixture files."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


LAB = Path(__file__).resolve().parents[1] / "scripts/sqlite_nfs_thread_lab.sh"


def run_child(tmp_path, *, net="net:[2]", initial="0", host_control="host:threads",
              bad_running=False, changed_binding=False):
    body = LAB.read_text().split("<<'CHILD' || lab_status=$?\n", 1)[1].split("\nCHILD", 1)[0]
    control = tmp_path / "control"
    control.mkdir()
    (control / "threads").write_text(initial + "\n")
    (control / "versions").write_text("+3 +4\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.jsonl"
    stub = '''
import json, os, pathlib, sys
name, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with open(os.environ['LAB_LOG'], 'a') as output:
    output.write(json.dumps([name, *args]) + '\\n')
if name == 'readlink':
    print(os.environ['LAB_NET'] if args[0].endswith('/net') else 'mnt:[2]')
elif name == 'stat':
    value = '6e667364' if '-f' in args else 'private:' + pathlib.Path(args[-1]).name
    if (os.environ['LAB_CHANGED_BINDING'] == '1' and args[-1].endswith('/threads')
            and pathlib.Path(args[-1]).read_text().strip() == '1'):
        value = 'changed:threads'
    print(value)
elif name == 'cat':
    value = pathlib.Path(args[0]).read_text().strip()
    if args[0].endswith('/versions') and value == '-4':
        value = '+3 -4'
    if args[0].endswith('/threads') and value == '1' and os.environ['LAB_BAD_RUNNING'] == '1':
        value = '2'
    print(value)
'''
    for name in ("mount", "umount", "readlink", "stat", "cat"):
        path = bin_dir / name
        path.write_text("#!" + sys.executable + "\n" + stub)
        path.chmod(0o700)
    result = subprocess.run(["bash", "-eu", "-s", "--", str(control), "net:[1]", "mnt:[1]", host_control],
                            input=body, capture_output=True, text=True, timeout=15,
                            env={**os.environ, "PATH": str(bin_dir) + os.pathsep + os.defpath,
                                 "LAB_LOG": str(log), "LAB_NET": net,
                                 "LAB_BAD_RUNNING": "1" if bad_running else "0",
                                 "LAB_CHANGED_BINDING": "1" if changed_binding else "0"})
    return result, control, [json.loads(line) for line in log.read_text().splitlines()]


def test_two_private_start_stop_cycles(tmp_path):
    result, control, calls = run_child(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "cycle=1 isolated_running_threads=1" in result.stdout
    assert "cycle=2 isolated_stopped_threads=0" in result.stdout
    assert (control / "threads").read_text() == "0\n"
    assert (control / "versions").read_text() == "-4\n"
    assert calls[-1] == ["umount", "--", str(control)]
    assert all(call[0] in {"mount", "umount", "stat", "readlink", "cat"} for call in calls)


def test_reused_network_namespace_stops_before_mount(tmp_path):
    result, control, calls = run_child(tmp_path, net="net:[1]")
    assert result.returncode == 2
    assert not any(call[0] == "mount" for call in calls)
    assert (control / "versions").read_text() == "+3 +4\n"


@pytest.mark.parametrize("options", [{"initial": "8"}, {"host_control": "private:threads"}])
def test_nonempty_or_reused_control_view_is_not_written(tmp_path, options):
    result, control, calls = run_child(tmp_path, **options)
    assert result.returncode == 2
    assert (control / "versions").read_text() == "+3 +4\n"
    assert (control / "threads").read_text().strip() == options.get("initial", "0")
    assert calls[-1] == ["umount", "--", str(control)]


def test_uncertain_start_cleans_up_only_bound_private_control(tmp_path):
    result, control, calls = run_child(tmp_path, bad_running=True)
    assert result.returncode != 0
    assert "private_cleanup_threads=0" in result.stdout
    assert (control / "threads").read_text() == "0\n"
    assert calls[-1] == ["umount", "--", str(control)]


def test_lost_binding_never_writes_stop_to_an_uncertain_control(tmp_path):
    result, control, calls = run_child(tmp_path, changed_binding=True)
    assert result.returncode == 2
    assert "private_cleanup_unverified" in result.stderr
    assert (control / "threads").read_text() == "1\n"
    assert calls[-1] == ["umount", "--", str(control)]
