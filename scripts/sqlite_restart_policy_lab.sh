#!/usr/bin/env bash
# Running-daemon, new-container-only policy fixture. No production controls.
set -euo pipefail
umask 077
[ "$#" = 1 ] && [ "$(uname -s)" = Linux ] || exit 2
parent=$1
case "$parent" in /*) :;; *) exit 2;; esac
case "$parent" in *[!a-zA-Z0-9_./-]*) exit 2;; esac
[ -d "$parent" ] && [ "$(readlink -f "$parent")" = "$parent" ]
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
image=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
docker image inspect "$image" >/dev/null
lab=$(mktemp -d "$parent/restart-policy.XXXXXX")
printf 'DISPOSABLE RESTART POLICY FIXTURE\n' > "$lab/.fixture-only"
printf 0 > "$lab/starts"
id=''
controller=''
label="restart-policy-${lab##*.}"
ours(){
  case "$id" in ''|*[!0-9a-f]*) return 1;; esac
  [ "${#id}" = 64 ] && [ "$(timeout 10 docker inspect --format '{{index .Config.Labels "org.nvmagma.auditor.fixture"}}' "$id")" = "$label" ]
}
cleanup(){
  if [ -n "$controller" ]; then kill "$controller" 2>/dev/null || :; wait "$controller" 2>/dev/null || :; controller=''; fi
  if [ -n "$id" ]; then
    ours || return 1
    timeout --kill-after=5s 20 docker rm -f "$id" >/dev/null || return 1
    id=''
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
printf 'production_activation=disabled\nwriter_exclusion_verified=false\nLab directory: %s\n' "$lab"
id=$(timeout 20 docker create --pull never --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --memory 64m --cpus 0.25 --pids-limit 32 \
  --restart on-failure:2 --label "org.nvmagma.auditor.fixture=$label" \
  --mount "type=bind,src=$lab,dst=/fixture" \
  --mount "type=bind,src=$repo/scripts/sqlite_restart_policy_actor.py,dst=/actor.py,readonly" \
  "$image" python -B /actor.py)
ours
timeout 15 docker start "$id" >/dev/null
await_starts(){
  for attempt in $(seq 1 100); do
    [ "$(cat "$lab/starts")" = "$1" ] && return 0
    sleep 0.2
  done
  return 1
}
await_starts 1
# Give Docker's restart monitor its documented successful-start interval.
sleep 11
touch "$lab/crash.1"
await_starts 2
ours
[ "$(timeout 10 docker inspect --format '{{.RestartCount}}' "$id")" = 1 ]
printf 'automatic_failure_restart_observed=true\n'
(
  ours
  timeout 15 docker update --restart=no "$id" >/dev/null
  ours
  [ "$(timeout 10 docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$id")" = no ]
  touch "$lab/controller-ready"
  exec sleep 60
) &
controller=$!
for attempt in $(seq 1 100); do
  [ -f "$lab/controller-ready" ] && break
  sleep 0.1
done
[ -f "$lab/controller-ready" ]
kill -KILL "$controller"
wait "$controller" 2>/dev/null || :
controller=''
sleep 11
touch "$lab/crash.2"
for attempt in $(seq 1 100); do
  ours
  [ "$(timeout 10 docker inspect --format '{{.State.Running}}' "$id")" = false ] && break
  sleep 0.1
done
# Observe for longer than the initial restart backoff; this is not a permanent fence.
sleep 5
ours
[ "$(timeout 10 docker inspect --format '{{.State.Running}} {{.State.ExitCode}} {{.RestartCount}} {{.HostConfig.RestartPolicy.Name}}' "$id")" = 'false 17 1 no' ]
[ "$(cat "$lab/starts")" = 2 ]
cleanup
trap - EXIT
printf '%s\n' 'status=isolated_restart_policy_complete' 'controller_killed=true' 'failed_writer_stayed_stopped=true' 'automatic_restoration=false' 'restart_inhibition_verified=false' 'Only a newly created fixture container was controlled; Docker daemon and production services unchanged.'
