#!/usr/bin/env bash
# Focused disposable boundary tests: new disposable dirs, read-only sources, no production mounts.
set -euo pipefail
umask 077
[ "$#" = 3 ] && [ "$(uname -s)" = Linux ] || exit 2
suite=$1
case "$suite" in copy-ownership|maintenance-writeback|maintenance-bound-copy) :;; *) exit 2;; esac
shift
for parent in "$@"; do
  case "$parent" in /*) :;; *) exit 2;; esac
  case "$parent" in *[!a-zA-Z0-9_./-]*) exit 2;; esac
  [ -d "$parent" ] && [ "$(readlink -f "$parent")" = "$parent" ]
done
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
image=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
docker image inspect "$image" >/dev/null
first=$(mktemp -d "$1/$suite.XXXXXX")
second=$(mktemp -d "$2/$suite.XXXXXX")
printf 'First lab: %s\nSecond lab: %s\n' "$first" "$second"
# Only pip dependency installation uses external networking. Tests use fake
# collectors and temporary files; no host .env/state/media or socket is mounted.
docker run --rm --pull never --network bridge --read-only --cap-drop ALL \
  --security-opt no-new-privileges --memory 512m --pids-limit 128 --cpus 2 \
  --label "org.nvmagma.auditor.fixture=$suite-tests" \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=256m \
  --mount "type=bind,src=$repo/app,dst=/src/app,readonly" \
  --mount "type=bind,src=$repo/tests,dst=/src/tests,readonly" \
  --mount "type=bind,src=$repo/scripts,dst=/src/scripts,readonly" \
  --mount "type=bind,src=$repo/requirements.txt,dst=/src/requirements.txt,readonly" \
  --mount "type=bind,src=$first,dst=/lab-first" \
  --mount "type=bind,src=$second,dst=/lab-second" \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/src -w /src \
  "$image" timeout --kill-after=5s 240s sh -eu -c '
    python -m venv /tmp/testenv
    /tmp/testenv/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir -r /src/requirements.txt pytest
    case "$1" in
      copy-ownership) set -- tests/test_sqlite_copy_hardlink_ownership.py tests/test_sqlite_copy_live_verification.py tests/test_sqlite_copy_nonblocking_reads.py;;
      maintenance-writeback) set -- tests/test_sqlite_maintenance_writeback_hold.py tests/test_sqlite_disposable_maintenance_journal.py tests/test_sqlite_disposable_maintenance_controller.py tests/test_sqlite_disposable_maintenance_writer.py tests/test_sqlite_maintenance_review.py;;
      maintenance-bound-copy) set -- tests/test_sqlite_maintenance_bound_copy.py tests/test_sqlite_maintenance_writeback_hold.py tests/test_sqlite_maintenance_review.py;;
      *) exit 2;;
    esac
    for path in /lab-first /lab-second; do
      printf "\nTesting: %s\n" "$path"
      /tmp/testenv/bin/python -B -m pytest -p no:cacheprovider --basetemp "$path/tests" -q --tb=short \
        "$@"
    done
  ' fixture-checks "$suite"
