import os
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:' + 'a' * 64
REVISION = 'b' * 40
CONTAINER = 'c' * 64


def fixture(tmp_path):
    tools = tmp_path / 'bin'; tools.mkdir()
    log = tmp_path / 'commands'
    docker = tools / 'docker'
    docker.write_text('''#!/usr/bin/env bash
set -eu
printf '%s\\n' "$@" >> "$FIXTURE_LOG"
if [ "$1 $2" = 'image inspect' ]; then
  case "$4" in
    *Entrypoint*) echo '["python","-m","app.main"]';;
    *StopSignal*) echo SIGINT;;
    *Volumes*) echo null;;
    *revision*) echo "$FIXTURE_REVISION";;
    *sqlite-activation*) echo "${FIXTURE_ACTIVATION:-disabled}";;
    *) echo "$FIXTURE_IMAGE";;
  esac
elif [ "$1" = create ]; then echo "$FIXTURE_CONTAINER"
elif [ "$1" = exec ]; then cat >/dev/null
elif [ "$1" = start ]; then [ "${START_FAIL:-no}" = no ]
elif [ "$1" = inspect ]; then
  if [ "${BAD_STOP:-no}" = yes ]; then echo 'false false 137'; else echo 'false false 0'; fi
elif [ "$1" = build ]; then
  cat >/dev/null
  while [ "$#" -gt 0 ]; do
    if [ "$1" = --iidfile ]; then printf '%s' "$FIXTURE_IMAGE" > "$2"; break; fi
    shift
  done
fi
''')
    git = tools / 'git'
    git.write_text('''#!/usr/bin/env bash
set -eu
case "$1" in
  branch) echo "${BUILD_BRANCH:-feature/sqlite}";;
  diff) [ "${DIRTY_INPUTS:-no}" = no ];;
  rev-parse) echo "$FIXTURE_REVISION";;
  archive|show) echo committed-fixture-bytes;;
  cat-file) exit 0;;
  *) exit 2;;
esac
''')
    docker.chmod(0o755); git.chmod(0o755)
    env = dict(os.environ, PATH=str(tools) + ':/usr/bin:/bin', FIXTURE_LOG=str(log),
        FIXTURE_IMAGE=IMAGE, FIXTURE_REVISION=REVISION, FIXTURE_CONTAINER=CONTAINER)
    return env, log


@pytest.mark.parametrize('branch', ['feature/sqlite','feature/unraid','feature/interface-api'])
@pytest.mark.parametrize('kind', ['candidate', 'preview_release'])
def test_host_python_free_build_never_tags_or_publishes(tmp_path, kind, branch):
    env, log = fixture(tmp_path)
    env["BUILD_BRANCH"] = branch
    result = subprocess.run(['bash', str(ROOT / f'scripts/sqlite_{kind}_build.sh')], env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == IMAGE
    commands = log.read_text()
    assert '--tag' not in commands and '--push' not in commands
    assert ('docker/sqlite-' + kind.replace('_', '-') + '.Dockerfile') in commands


@pytest.mark.parametrize('option', ['BUILD_BRANCH', 'DIRTY_INPUTS'])
@pytest.mark.parametrize('kind', ['candidate', 'preview_release'])
def test_bad_branch_or_dirty_build_cannot_reach_docker(tmp_path, option, kind):
    env, log = fixture(tmp_path)
    env[option] = 'main' if option == 'BUILD_BRANCH' else 'yes'
    result = subprocess.run(['bash', str(ROOT / f'scripts/sqlite_{kind}_build.sh')], env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode != 0 and not log.exists()


@pytest.mark.parametrize('failure', [None, 'START_FAIL', 'BAD_STOP'])
def test_image_lab_isolated_and_cleans_only_new_container(tmp_path, failure):
    env, log = fixture(tmp_path)
    if failure: env[failure] = 'yes'
    result = subprocess.run(['bash', str(ROOT / 'scripts/sqlite_candidate_image_lab.sh'), IMAGE], env=env,
                            capture_output=True, text=True, timeout=15)
    assert (result.returncode == 0) is (failure is None), result.stderr
    assert ('candidate_image_acceptance_complete' in result.stdout) is (failure is None)
    commands = log.read_text()
    assert '--network\nnone' in commands and '--read-only' in commands
    assert '--mount' not in commands and '--publish' not in commands
    assert '/var/run/docker.sock' not in commands
    assert commands.endswith('rm\n--force\n' + CONTAINER + '\n')
