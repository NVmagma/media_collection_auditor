#!/usr/bin/env bash
# No real Docker socket mounted. Docker commands target ONLY new fixture IDs.
set -euo pipefail
if [ "$#" != 1 ] || [ "$(uname -s)" != Linux ]; then
  printf '%s\n' 'Usage: bash scripts/sqlite_docker_control_lab.sh EXISTING_ABSOLUTE_LAB_PARENT' >&2
  exit 2
fi
parent=$1
case "$parent" in /*) :;; *) exit 2;; esac
case "$parent" in *[!a-zA-Z0-9_./-]*) exit 2;; esac
[ -d "$parent" ] && [ "$(readlink -f "$parent")" = "$parent" ]
for dependency in docker readlink mktemp mkdir dirname timeout cat seq sleep touch grep; do
  command -v "$dependency" >/dev/null
done
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
image=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
docker image inspect "$image" >/dev/null
lab=$(mktemp -d "$parent/docker-control.XXXXXX")
mkdir "$lab/daemon" "$lab/commands"
for target in daemon commands; do
  printf 'DISPOSABLE DOCKER CONTROL FIXTURE ONLY\n' > "$lab/$target/.disposable_docker_control"
done
printf '0' > "$lab/daemon/calls"
daemon_id=
actor_id=
controller_pid=
cleanup(){
  original_status=$?
  trap - EXIT
  if [ -n "$controller_pid" ]; then
    kill -KILL "$controller_pid" 2>/dev/null || true
    wait "$controller_pid" 2>/dev/null || true
  fi
  # End the private endpoint FIRST; removing a frozen client must not briefly
  # make its pending request actionable. No production socket is accessible.
  if [ -n "$daemon_id" ] && ! docker rm -f "$daemon_id" >/dev/null 2>&1; then
    printf '%s\n' 'blocked=private_endpoint_cleanup_failed; paused actor retained' >&2
    exit 2
  fi
  if [ -n "$actor_id" ] && ! docker rm -f "$actor_id" >/dev/null 2>&1; then
    printf '%s\n' 'blocked=private_actor_cleanup_failed' >&2
    exit 2
  fi
  exit "$original_status"
}
trap cleanup EXIT
printf '%s\n' 'production_activation=disabled' 'writer_exclusion_verified=false'
printf 'Lab directory: %s\n' "$lab"
daemon_id=$(docker create --pull=never --network none --read-only --cap-drop ALL --restart no \
  --label media-auditor.disposable-docker-control=true --security-opt no-new-privileges \
  --mount "type=bind,src=$repo,dst=/src,readonly" \
  --mount "type=bind,src=$lab/daemon,dst=/fixture" \
  "$image" python -B /src/scripts/sqlite_docker_control_lab.py --role serve)
docker start "$daemon_id" >/dev/null
for attempt in $(seq 1 100); do
  [ ! -f "$lab/daemon/server.ready" ] || break
  [ "$(docker inspect --format '{{.State.Running}}' "$daemon_id")" = true ]
  sleep 0.05
done
[ -S "$lab/daemon/api.sock" ] && [ -f "$lab/daemon/server.ready" ]
actor_id=$(docker create --pull=never --network none --read-only --cap-drop ALL --restart no \
  --label media-auditor.disposable-docker-control=true --security-opt no-new-privileges \
  --mount "type=bind,src=$repo,dst=/src,readonly" \
  --mount "type=bind,src=$lab/commands,dst=/commands,readonly" \
  --mount "type=bind,src=$lab/daemon/api.sock,dst=/run/fixture.sock,readonly" \
  "$image" python -B /src/scripts/sqlite_docker_control_lab.py --role actor)
docker start "$actor_id" >/dev/null
# Wait until the client completed its GET handshake, before creating command 1.
# The live connection is independently visible in the actor's readiness marker
# via its log message; no writable client filesystem is needed.
ready=0
for attempt in $(seq 1 100); do
  if docker logs "$actor_id" 2>/dev/null | grep -q '^actor_connection_ready$'; then ready=1; break; fi
  [ "$(docker inspect --format '{{.State.Running}}' "$actor_id")" = true ]
  sleep 0.05
done
[ "$ready" = 1 ]
touch "$lab/commands/request.1"
for attempt in $(seq 1 100); do
  [ "$(cat "$lab/daemon/calls")" != 1 ] || break
  sleep 0.05
done
[ "$(cat "$lab/daemon/calls")" = 1 ]
printf '%s\n' 'read_only_socket_fixture_api_call_observed=true'
pause_controller(){
  docker pause "$actor_id" > "$lab/pause-controller.log"
  touch "$lab/controller-paused"
  while :; do sleep 1; done
}
pause_controller &
controller_pid=$!
for attempt in $(seq 1 100); do
  [ ! -f "$lab/controller-paused" ] || break
  sleep 0.05
done
[ -f "$lab/controller-paused" ]
[ "$(docker inspect --format '{{.State.Paused}}' "$actor_id")" = true ]
kill -KILL "$controller_pid"
result=0
wait "$controller_pid" 2>/dev/null || result=$?
controller_pid=
[ "$result" = 137 ]
touch "$lab/commands/request.2"
sleep 0.5
timeout --kill-after=5s 10s docker exec "$daemon_id" \
  python -B /src/scripts/sqlite_docker_control_lab.py --role probe
[ "$(cat "$lab/daemon/calls")" = 1 ]
[ "$(docker inspect --format '{{.State.Paused}}' "$actor_id")" = true ]
printf '%s\n' 'pause_controller_killed=true' 'fixture_api_calls_after_controller_death=1' \
  'automatic_restoration=false' 'restart_inhibition_verified=false' \
  'status=isolated_docker_control_pause_complete' \
  'No real Docker socket was mounted; only new fixture containers were paused/removed.'
