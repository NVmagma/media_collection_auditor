#!/usr/bin/env bash
# Two disposable containers, separate networks, retained lab only. No NFS controls.
set -euo pipefail
if [ "$#" != 1 ] || [ "$(uname -s)" != Linux ]; then
  printf '%s\n' 'Usage: bash scripts/sqlite_maintenance_scope_lab.sh EXISTING_ABSOLUTE_LAB_PARENT' >&2
  exit 2
fi
parent=$1
case "$parent" in /*) :;; *) exit 2;; esac
case "$parent" in *[!a-zA-Z0-9_./-]*) exit 2;; esac
[ -d "$parent" ] && [ "$(readlink -f "$parent")" = "$parent" ]
for dependency in docker readlink mktemp mkdir seq sleep timeout sha256sum dirname; do
  command -v "$dependency" >/dev/null
done
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
image=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
docker image inspect "$image" >/dev/null
lab=$(mktemp -d "$parent/maintenance-scope.XXXXXX")
mkdir "$lab/control"
printf 'DISPOSABLE MAINTENANCE SCOPE LAB\n' > "$lab/control/.disposable_maintenance_scope"
writer_id=
checker_id=
cleanup(){
  if [ -n "$checker_id" ]; then docker rm -f "$checker_id" >/dev/null 2>&1 || true; fi
  if [ -n "$writer_id" ]; then docker rm -f "$writer_id" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT
printf '%s\n' 'production_activation=disabled' 'writer_exclusion_verified=false'
printf 'Lab directory: %s\n' "$lab"
writer_id=$(docker create --pull=never --network none --read-only --cap-drop ALL \
  --label media-auditor.disposable-maintenance-scope=true \
  --security-opt no-new-privileges -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/src \
  -v "$repo:/src:ro" -v "$lab/control:/control:rw" \
  "$image" python -B /src/scripts/sqlite_maintenance_scope_lab.py --role prepare)
docker start "$writer_id" >/dev/null
for attempt in $(seq 1 100); do
  [ ! -f "$lab/control/writer.ready" ] || break
  if [ "$(docker inspect --format '{{.State.Running}}' "$writer_id")" != true ]; then
    docker logs "$writer_id"
    exit 2
  fi
  sleep 0.1
done
[ -f "$lab/control/writer.ready" ]
before=$(sha256sum "$lab/control/maintenance-journal/maintenance.db")
# Same container/network/path, but a new interpreter/PID cannot inherit the
# original session. This attempts a transition only against the new lab DB.
timeout --kill-after=5s 20s docker exec "$writer_id" \
  python -B /src/scripts/sqlite_maintenance_scope_lab.py --role reject-other-controller
[ "$(sha256sum "$lab/control/maintenance-journal/maintenance.db")" = "$before" ]
checker_id=$(docker create --pull=never --network none --read-only --cap-drop ALL \
  --label media-auditor.disposable-maintenance-scope=true \
  --security-opt no-new-privileges -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/src \
  -v "$repo:/src:ro" -v "$lab/control:/control:ro" \
  "$image" python -B /src/scripts/sqlite_maintenance_scope_lab.py --role reject-other-network)
# Bound execution; cleanup removes only the two newly created container IDs.
timeout --kill-after=5s 20s docker start -a "$checker_id"
[ "$(docker inspect --format '{{.State.ExitCode}}' "$checker_id")" = 0 ]
[ "$(docker inspect --format '{{.State.Running}}' "$writer_id")" = true ]
[ "$(sha256sum "$lab/control/maintenance-journal/maintenance.db")" = "$before" ]
printf '%s\n' 'journal_bytes_unchanged=true' 'status=isolated_scope_check_complete' \
  'No NFS control, service, export, production mount or startup configuration was changed.'
