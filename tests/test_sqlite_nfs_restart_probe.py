"""Read-only preference parsing must not expose unrelated settings or run them."""
from pathlib import Path
import subprocess

import pytest


PROBE = Path(__file__).resolve().parents[1] / "scripts/sqlite_nfs_restart_probe.sh"


@pytest.mark.parametrize("data, expected", [
    ('shareNFSEnabled="yes"\nsecret="hidden"\n', "yes"),
    ('shareNFSEnabled="no"\r\n', "no"),
    ('shareNFSEnabled="yes"\nshareNFSEnabled="no"\n', "unverified"),
    ('shareNFSEnabled="maybe"\n', "unverified"),
    ('shareNFSEnabled="$(touch unexpected)"\n', "unverified"),
    ('secret="hidden"\n', "unverified"),
])
def test_selected_preference_never_evaluates_or_dumps_configuration(tmp_path, data, expected):
    source = PROBE.read_text()
    function = "observe_preference(){\n" + source.split("observe_preference(){\n", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    settings = tmp_path / "settings.cfg"
    settings.write_text(data)
    result = subprocess.run(["bash", "-eu", "-s", "--", str(settings)],
                            input=function + 'observe_preference "$1"\n',
                            cwd=tmp_path, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["settings_file=" + str(settings), "shareNFSEnabled=" + expected]
    assert not (tmp_path / "unexpected").exists()


def test_arguments_refused_before_host_reads():
    result = subprocess.run(["bash", str(PROBE), "status"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "source_file=" not in result.stdout


@pytest.mark.parametrize("case", ["matching", "changed", "missing"])
def test_source_identity_is_observed_without_executing_boot_code(tmp_path, case):
    import hashlib

    source = PROBE.read_text()
    function = "observe_source(){\n" + source.split("observe_source(){\n", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    script = tmp_path / "rc.local"
    content = b"#!/bin/bash\ntouch unexpected\n"
    if case != "missing":
        script.write_bytes(content)
        script.chmod(0o755)
    expected = hashlib.sha256(content if case == "matching" else b"other").hexdigest()
    result = subprocess.run(["bash", "-eu", "-s", "--", str(script), expected],
                            input=function + 'observe_source "$1" "$2"\n',
                            cwd=tmp_path, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    if case == "missing":
        assert "source_identity=unavailable" in result.stdout
        assert "matches_reviewed_upstream=true" not in result.stdout
    else:
        assert "matches_reviewed_upstream=" + str(case == "matching").lower() in result.stdout
    assert not (tmp_path / "unexpected").exists()


def test_boot_observations_use_only_fixed_reviewed_source_paths():
    source = PROBE.read_text()
    for name in ("rc.S", "rc.M", "rc.inet2", "rc.local"):
        assert "observe_source /etc/rc.d/" + name + " " in source
    assert "observe_source /boot/config/go" not in source
