from pathlib import Path
import subprocess

import pytest

REPO=Path(__file__).resolve().parents[1]
LAUNCHER=REPO/'scripts/sqlite_host_controller_native.sh'


@pytest.mark.parametrize('arguments,message',[
    (['start','/unused','/unused','/unused','a'*64,'b'*64],'Preparation/review mode required'),
    (['prepare','/unused','/unused','/unused','latest','b'*64],'Reviewed SHA-256 values required'),
    (['prepare','/unused','/unused','/unused','a'*64,'bad'],'Reviewed SHA-256 values required'),
])
def test_invalid_actions_or_hashes_rejected_before_runtime_access(arguments,message):
    # Override only the platform observation in this shell. No runtime command
    # can be reached because mode/hash validation precedes path access.
    result=subprocess.run(['/bin/bash','-p','-c',
        'uname() { printf "Linux\\n"; }; source "$1" "${@:2}"','fixture',str(LAUNCHER),*arguments],
        capture_output=True,text=True,timeout=10)
    assert result.returncode!=0
    assert message in result.stderr


def test_native_shell_files_parse_without_execution():
    for name in ('sqlite_host_controller_native.sh','sqlite_host_controller_native_lab.sh'):
        result=subprocess.run(['/bin/bash','-n',str(REPO/'scripts'/name)],capture_output=True)
        assert result.returncode==0


def test_native_fixture_refuses_non_fixture_host_without_creating_state(tmp_path):
    from scripts.sqlite_host_controller_native_lab import run
    root=tmp_path.resolve()/'must-not-exist'
    with pytest.raises(RuntimeError,match='Dedicated native controller container required'):run(root)
    assert not root.exists()
