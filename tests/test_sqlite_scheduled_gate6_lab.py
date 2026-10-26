import os
from pathlib import Path
import subprocess

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/sqlite_scheduled_gate6_lab.sh'
IMAGE = 'sha256:' + 'a' * 64
CONTAINER = 'b' * 64


def run_lab(tmp_path, **changes):
    tools = tmp_path / 'tools'; tools.mkdir()
    base = tmp_path / 'labs'; base.mkdir()
    (base / 'existing').write_text('preserve')
    log = tmp_path / 'calls'
    (tools / 'uname').write_text('#!/bin/sh\necho Linux\n')
    (tools / 'uname').chmod(0o700)
    git = tools / 'git'
    git.write_text('#!/bin/sh\nif [ "$1" = diff ]; then exit 0; fi\nexec /usr/bin/git "$@"\n')
    git.chmod(0o700)
    docker = tools / 'docker'
    docker.write_text('''#!/bin/bash
printf 'CALL\\n' >> "$FIXTURE_CALL_LOG"
printf '%s\\n' "$@" >> "$FIXTURE_CALL_LOG"
case "$1" in
image)
  if [ "$4" = '{{.Id}}' ]; then printf '%s\\n' "$FIXTURE_IMAGE_ID"; else echo "${FIXTURE_VOLUMES:-null}"; fi ;;
create) printf '%s\\n' "$FIXTURE_CONTAINER_ID" ;;
start) cat >/dev/null; [ "${FIXTURE_START_FAIL:-no}" = no ] || exit 1; echo fixture_passed ;;
inspect) echo '0 false' ;;
rm) printf '%s\\n' "$FIXTURE_CONTAINER_ID" ;;
*) exit 2 ;;
esac
''')
    docker.chmod(0o700)
    env = {**os.environ, 'PATH': str(tools) + os.pathsep + os.defpath,
           'FIXTURE_CALL_LOG': str(log), 'FIXTURE_IMAGE_ID': IMAGE, 'FIXTURE_CONTAINER_ID': CONTAINER,
           'SQLITE_LAB_IMAGE': IMAGE, **changes}
    result = subprocess.run(['/bin/bash', str(SCRIPT), str(base)], env=env,
                            capture_output=True, text=True, timeout=20)
    return result, base, log


def test_only_new_lab_is_bound_and_new_container_is_removed(tmp_path):
    result, base, log = run_lab(tmp_path)
    assert result.returncode == 0, result.stderr
    assert 'status=scheduled_gate6_acceptance_complete' in result.stdout
    assert (base / 'existing').read_text() == 'preserve'
    labs = list(base.glob('scheduled-gate6.*')); assert len(labs) == 1
    calls = log.read_text()
    assert f'type=bind,src={labs[0]},dst=/lab' in calls
    assert '--cap-drop\nALL' in calls and '--network\nnone' in calls
    assert '--privileged' not in calls and '/var/run/docker.sock' not in calls
    assert calls.endswith('rm\n--force\n' + CONTAINER + '\n')


def test_fixture_failure_removes_only_fixture_and_does_not_report_success(tmp_path):
    result, base, log = run_lab(tmp_path, FIXTURE_START_FAIL='yes')
    assert result.returncode != 0
    assert 'status=scheduled_gate6_acceptance_complete' not in result.stdout
    assert log.read_text().endswith('rm\n--force\n' + CONTAINER + '\n')
    assert (base / 'existing').read_text() == 'preserve'


def test_mutable_image_refused_before_docker_or_lab_creation(tmp_path):
    result, base, log = run_lab(tmp_path, SQLITE_LAB_IMAGE='python:latest')
    assert result.returncode == 2 and not log.exists()
    assert list(base.iterdir()) == [base / 'existing']


def test_image_volumes_refused_before_new_lab(tmp_path):
    result, base, log = run_lab(tmp_path, FIXTURE_VOLUMES='{"/media":{}}')
    assert result.returncode == 2
    assert list(base.iterdir()) == [base / 'existing']
