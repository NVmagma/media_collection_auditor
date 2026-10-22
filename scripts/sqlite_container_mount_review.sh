#!/usr/bin/env bash
# Selected-field Docker snapshot only. Never stop/update/remount a container.
set -euo pipefail
if [ "$#" -lt 1 ]; then
  printf '%s\n' 'Usage: bash scripts/sqlite_container_mount_review.sh ABS_MEDIA_ROOT [ABS_MEDIA_ROOT...]' >&2
  exit 2
fi
arguments=()
for root in "$@"; do arguments+=(--media-root "$root"); done
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
image=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
docker image inspect "$image" >/dev/null
# Enumerate before starting the observer; its own container is not in the list.
container_ids=$(docker ps -aq)
{
  for id in $container_ids; do
    if ! docker inspect --type container --format \
'{"kind":"container","name":{{json .Name}},"running":{{json .State.Running}},"paused":{{json .State.Paused}},"restart":{{json .HostConfig.RestartPolicy.Name}},"privileged":{{json .HostConfig.Privileged}},"pid_mode":{{json .HostConfig.PidMode}},"cap_add":{{json .HostConfig.CapAdd}},"device_count":{{len .HostConfig.Devices}},"mounts":{{json .Mounts}}}' "$id"; then
      exit 2
    fi
  done
  printf '%s\n' '{"kind":"end"}'
} | docker run --rm -i --pull=never --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges -e PYTHONPATH=/src \
  --mount "type=bind,src=$repo,dst=/src,readonly" \
  "$image" python -B /src/scripts/sqlite_container_mount_review.py "${arguments[@]}"
