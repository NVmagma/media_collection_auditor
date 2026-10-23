import os
from pathlib import Path
import subprocess

import pytest

PROBE = Path(__file__).parents[1] / 'scripts/sqlite_nfs_mac_client_probe.sh'


def run(tmp_path, data, system='Darwin', args=(), fail=False):
    tools = tmp_path / 'bin'
    tools.mkdir()
    for name, body in {
        'uname': 'echo ' + system,
        'sw_vers': 'echo 26.0',
        'nfsstat': 'cat "$PROBE_INPUT"; exit ' + ('1' if fail else '0'),
        'mount': 'touch "$PROBE_MUTATED"; exit 99',
        'sudo': 'touch "$PROBE_MUTATED"; exit 99',
        'sysctl': 'touch "$PROBE_MUTATED"; exit 99',
    }.items():
        target = tools / name
        target.write_text('#!/bin/sh\n' + body + '\n')
        target.chmod(0o755)
    source = tmp_path / 'input'
    source.write_text(data)
    result = subprocess.run(['bash', str(PROBE), *args], capture_output=True, text=True,
                            timeout=10, env={**os.environ, 'PATH':str(tools)+os.pathsep+os.environ['PATH'],
                            'PROBE_INPUT':str(source), 'PROBE_MUTATED':str(tmp_path/'mutated')})
    assert not (tmp_path/'mutated').exists()
    return result


def test_current_options_selected_without_paths_or_original_defaults(tmp_path):
    result = run(tmp_path, '''/Volumes/secret from private-server:/private/export
  -- Original mount options:
     NFS parameters: vers=4,tcp,soft
  -- Current mount parameters:
     NFS parameters: vers=3,tcp,hard,intr,rsize=65536,wsize=65536,timeo=10,retrans=10,sec=secret
/Volumes/other from another-secret:/export
  -- Current mount parameters:
     NFS parameters: vers=4.1,tcp,soft,deadtimeout=30
''')
    assert result.returncode == 0
    assert 'current_option=vers=3' in result.stdout
    assert 'current_option=vers=4.1' in result.stdout
    assert 'current_option=vers=4\n' not in result.stdout
    assert 'mount_records_observed=2' in result.stdout
    assert 'secret' not in result.stdout
    assert '/Volumes' not in result.stdout
    assert 'current_option=hard' in result.stdout


@pytest.mark.parametrize('data', ['', '/Volumes/private from private:/share\n  -- Original mount options:\n     NFS parameters: vers=3,tcp\n'])
def test_no_current_mount_is_unknown_not_a_denial_permit(tmp_path, data):
    result = run(tmp_path, data)
    assert result.returncode == 0
    assert 'mount_records_observed=0' in result.stdout
    assert 'current_option=' not in result.stdout
    assert 'writer_exclusion_verified=false' in result.stdout


@pytest.mark.parametrize('system,args', [('Linux', ()), ('Darwin', ('mount',))])
def test_wrong_platform_and_arguments_rejected(tmp_path, system, args):
    result = run(tmp_path, '', system=system, args=args)
    assert result.returncode == 2
    assert 'macos_version=' not in result.stdout


def test_failed_nfsstat_cannot_report_success(tmp_path):
    result = run(tmp_path, '', fail=True)
    assert result.returncode != 0
    assert 'status=mac_client_options_observed' not in result.stdout
