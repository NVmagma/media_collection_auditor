import os
from pathlib import Path
import subprocess

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.mark.parametrize("arguments", [[], ["start"], ["restart"], ["update"], ["reload"],
                                       ["status"], ["stop"], ["unknown", "extra"]])
def test_guard_denies_before_any_environment_startup_or_dispatch(tmp_path, arguments):
    guard = tmp_path / "rc.nfsd"
    guard.write_bytes((SCRIPTS / "sqlite_nfs_restart_guard.sh").read_bytes())
    guard.chmod(0o555)
    startup = tmp_path / "startup.sh"
    startup.write_text(': > "$NFS_GUARD_STARTUP_MARKER"\n')
    result = subprocess.run([str(guard), *arguments], capture_output=True, text=True, timeout=10,
                            env={"PATH": str(tmp_path), "BASH_ENV": str(startup),
                                 "NFS_GUARD_STARTUP_MARKER": str(tmp_path / "startup-executed"),
                                 "NFS_GUARD_FUNCTION_MARKER": str(tmp_path / "function-executed"),
                                 "BASH_FUNC_printf%%": '() { : > "$NFS_GUARD_FUNCTION_MARKER"; }'})
    assert result.returncode == 75
    assert result.stdout == ""
    assert result.stderr == "NFS service dispatch denied by maintenance guard\n"
    assert not (tmp_path / "startup-executed").exists()
    assert not (tmp_path / "function-executed").exists()


def test_helper_refuses_standalone_host_invocation():
    result = subprocess.run(["bash", str(SCRIPTS / "sqlite_nfs_restart_entrypoint_lab.sh")],
                            capture_output=True, text=True, timeout=10, env={**os.environ, "scenario": ""})
    assert result.returncode == 2
    assert "private_supervisor_required" in result.stderr
