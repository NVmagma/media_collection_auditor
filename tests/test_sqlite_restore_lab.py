from pathlib import Path
import subprocess
import pytest
from tests.test_sqlite_candidate_shell import fixture, IMAGE, CONTAINER

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('failure', [None, 'START_FAIL'])
@pytest.mark.parametrize('kind', ['restore', 'release_preparation'])
def test_only_new_lab_is_mounted_and_fixture_container_removed(tmp_path, failure, kind):
    env, log = fixture(tmp_path)
    tools = Path(env['PATH'].split(':')[0])
    (tools/'uname').write_text('#!/usr/bin/env bash\necho Linux\n'); (tools/'uname').chmod(0o755)
    docker = tools/'docker'
    text = docker.read_text().replace("echo 'false false 0'", "echo '0 false'")
    text = text.replace("elif [ \"$1\" = start ]; then", 'elif [ "$1" = start ]; then\n  if [ "${2:-}" = --attach ]; then cat >/dev/null; fi\n')
    docker.write_text(text)
    base = (tmp_path/'labs'); base.mkdir(); (base/'existing').write_text('preserve')
    if failure: env[failure] = 'yes'
    script = ROOT / f'scripts/sqlite_{kind}_lab.sh'
    result = subprocess.run(['bash', str(script), IMAGE, str(base.resolve())], env=env,
                            capture_output=True, text=True, timeout=15)
    assert (result.returncode == 0) is (failure is None), result.stderr
    assert (kind + '_acceptance_complete' in result.stdout) is (failure is None)
    assert (base/'existing').read_text() == 'preserve'
    labs = list(base.glob(kind.replace('_', '-') + '.*')); assert len(labs) == 1
    commands = log.read_text()
    assert 'type=bind,src=' + str(labs[0].resolve()) + ',dst=/lab' in commands
    assert '/var/run/docker.sock' not in commands and '--publish' not in commands
    assert commands.endswith('rm\n--force\n' + CONTAINER + '\n')


@pytest.mark.parametrize('kind', ['restore', 'release_preparation'])
def test_alias_parent_rejected_before_docker(tmp_path, kind):
    env, log = fixture(tmp_path)
    tools = Path(env['PATH'].split(':')[0])
    (tools/'uname').write_text('#!/usr/bin/env bash\necho Linux\n'); (tools/'uname').chmod(0o755)
    actual = tmp_path/'actual'; actual.mkdir()
    alias = tmp_path/'alias'; alias.symlink_to(actual, target_is_directory=True)
    script = ROOT / f'scripts/sqlite_{kind}_lab.sh'
    result = subprocess.run(['bash', str(script), IMAGE, str(alias)], env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode != 0 and not log.exists()
