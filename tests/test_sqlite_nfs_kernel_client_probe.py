"""Probe selected values without helpers, mounts, module loads or config eval."""
import os
from pathlib import Path
import subprocess

import pytest

PROBE = Path(__file__).resolve().parents[1] / "scripts/sqlite_nfs_kernel_client_probe.sh"


def function(name):
    return name + "(){\n" + PROBE.read_text().split(name + "(){\n", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


@pytest.mark.parametrize("value, expected", [("Y\n", "Y"), ("N\n", "N"), ("1\n", "1"),
                                            ("$(touch executed)\n", "unverified"),
                                            ("yes\n", "unverified"), ("Y\nN\n", "unverified")])
def test_boolean_observation_never_evaluates_parameter_content(tmp_path, value, expected):
    source = tmp_path / "parameter"
    source.write_text(value)
    result = subprocess.run(["bash", "-eu", "-s", "--", str(source)],
                            input=function("observe_boolean") + 'observe_boolean "$1" localio_enabled\n',
                            cwd=tmp_path, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0
    assert result.stdout == "localio_enabled=" + expected + "\n"
    assert not (tmp_path / "executed").exists()


def test_filesystem_observation_uses_exact_registration_name(tmp_path):
    source = tmp_path / "filesystems"
    source.write_text("nodev\tnfsd\nnodev\tnfs4\nnodev\tnfs_extra\n")
    result = subprocess.run(["bash", "-eu", "-s", "--", str(source)],
                            input=function("observe_filesystem") + 'observe_filesystem "$1" nfs\nobserve_filesystem "$1" nfs4\n',
                            text=True, capture_output=True, timeout=10)
    assert result.stdout.splitlines() == ["filesystem_nfs=not_registered", "filesystem_nfs4=registered"]


def test_kernel_config_output_is_selected_and_never_sourced(tmp_path):
    data = "CONFIG_NFS_FS=m\nCONFIG_NFS_LOCALIO=y\n# CONFIG_NFS_V4_2 is not set\nCONFIG_SECRET=private\ntouch executed\n"
    result = subprocess.run(["bash", "-eu", "-s"], input=function("select_config") + "select_config <<'DATA'\n" + data + "DATA\n",
                            cwd=tmp_path, text=True, capture_output=True, timeout=10)
    assert result.stdout.splitlines() == ["CONFIG_NFS_FS=m", "CONFIG_NFS_LOCALIO=y", "# CONFIG_NFS_V4_2 is not set"]
    assert not (tmp_path / "executed").exists()


def test_probe_hashes_helper_without_executing_it(tmp_path):
    directory = tmp_path / "bin"
    directory.mkdir()
    helper = directory / "mount.nfs"
    helper.write_text('#!/bin/sh\ntouch "$PROBE_HELPER_EXECUTED"\n')
    helper.chmod(0o755)
    uname = directory / "uname"
    uname.write_text('#!/bin/sh\ncase "$1" in -s) echo Linux;; -r) echo 6.12-fixture;; esac\n')
    uname.chmod(0o755)
    result = subprocess.run(["bash", str(PROBE)], capture_output=True, text=True, timeout=10,
                            env={**os.environ, "PATH": str(directory) + os.pathsep + os.environ["PATH"],
                                 "PROBE_HELPER_EXECUTED": str(tmp_path / "executed")})
    assert result.returncode == 0, result.stderr
    assert "mount_helper_path=" + str(helper) in result.stdout
    assert "module_loads_performed=false" in result.stdout
    assert "kernel_mounts_performed=false" in result.stdout
    assert not (tmp_path / "executed").exists()


def test_arguments_refused_before_observations():
    result = subprocess.run(["bash", str(PROBE), "mount"], text=True, capture_output=True, timeout=10)
    assert result.returncode == 2
    assert "kernel_release=" not in result.stdout


def test_module_metadata_queries_running_release_without_loading_modules(tmp_path):
    tool = tmp_path / "modinfo"
    log = tmp_path / "queries"
    tool.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$METADATA_QUERY_LOG"
case "$4" in
filename) printf '/lib/modules/6.18-fixture/kernel/fs/nfs/nfs.ko.xz\\n';;
vermagic) printf '6.18-fixture SMP preempt mod_unload\\n';;
depends) printf 'sunrpc,lockd,nfslocalio\\n';;
parmtype) printf 'unselected:charp\\nlocalio_enabled:bool\\nlocalio_O_DIRECT_semantics:bool\\n';;
*) exit 2;;
esac
''')
    tool.chmod(0o755)
    code = 'release=6.18-fixture\nmodinfo_tool=$1\n' + function("observe_module") + 'observe_module nfs\n'
    result = subprocess.run(["bash", "-eu", "-s", "--", str(tool)], input=code,
                            text=True, capture_output=True, timeout=10,
                            env={**os.environ, "METADATA_QUERY_LOG": str(log)})
    assert result.returncode == 0, result.stderr
    assert "module_nfs_vermagic=6.18-fixture SMP preempt mod_unload" in result.stdout
    assert "module_nfs_depends=sunrpc,lockd,nfslocalio" in result.stdout
    assert "module_nfs_parameter=localio_enabled:bool" in result.stdout
    assert "unselected" not in result.stdout
    assert all(query.startswith("-k 6.18-fixture -F ") and query.endswith(" nfs")
               for query in log.read_text().splitlines())


@pytest.mark.parametrize("value", ["unavailable", "wrong_kernel"])
def test_module_metadata_failure_never_becomes_a_load_or_available_claim(tmp_path, value):
    tool = tmp_path / "modinfo"
    body = "exit 1\n" if value == "unavailable" else "printf '/lib/modules/wrong/kernel/nfs.ko\\n'\n"
    tool.write_text("#!/bin/sh\n" + body)
    tool.chmod(0o755)
    code = 'release=6.18-fixture\nmodinfo_tool=$1\n' + function("observe_module") + 'observe_module nfs\n'
    result = subprocess.run(["bash", "-eu", "-s", "--", str(tool)], input=code,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0
    assert "module_nfs_metadata=" + ("unavailable" if value == "unavailable" else "unverified") in result.stdout
    assert "module_nfs_vermagic=" not in result.stdout
