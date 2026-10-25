from pathlib import Path
import subprocess
import pytest
from tests.test_sqlite_candidate_shell import fixture, IMAGE, CONTAINER

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/sqlite_restore_lab.sh'


@pytest.mark.parametrize('failure', [None, 'START_FAIL'])
def test_only_new_lab_is_mounted_and_fixture_container_removed(tmp_path, failure):
    env, log = fixture(tmp_path)
    tools = Path(env['PATH'].split(':')[0])
    (tools/'uname').write_text('#!/usr/bin/env bash\necho Linux\n'); (tools/'uname').chmod(0o755)
    docker = tools/'docker'
    text = docker.read_text().replace("echo 'false false 0'", "echo '0 false'")
    text = text.replace("elif [ \"$1\" = start ]; then", 'elif [ "$1" = start ]; then\n  if [ "${2:-}" = --attach ]; then cat >/dev/null; fi\n')
    docker.write_text(text)
    base = (tmp_path/'labs'); base.mkdir(); (base/'existing').write_text('preserve')
    if failure: env[failure] = 'yes'
    result = subprocess.run(['bash', str(SCRIPT), IMAGE, str(base.resolve())], env=env,
                            capture_output=True, text=True, timeout=15)
    assert (result.returncode == 0) is (failure is None), result.stderr
    assert ('restore_acceptance_complete' in result.stdout) is (failure is None)
    assert (base/'existing').read_text() == 'preserve'
    labs = list(base.glob('restore.*')); assert len(labs) == 1
    commands = log.read_text()
    assert 'type=bind,src=' + str(labs[0].resolve()) + ',dst=/lab' in commands
    assert '/var/run/docker.sock' not in commands and '--publish' not in commands
    assert commands.endswith('rm\n--force\n' + CONTAINER + '\n')


def test_alias_parent_rejected_before_docker(tmp_path):
    env, log = fixture(tmp_path)
    tools = Path(env['PATH'].split(':')[0])
    (tools/'uname').write_text('#!/usr/bin/env bash\necho Linux\n'); (tools/'uname').chmod(0o755)
    actual = tmp_path/'actual'; actual.mkdir()
    alias = tmp_path/'alias'; alias.symlink_to(actual, target_is_directory=True)
    result = subprocess.run(['bash', str(SCRIPT), IMAGE, str(alias)], env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode != 0 and not log.exists()
