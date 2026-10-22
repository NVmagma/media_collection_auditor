#!/usr/bin/env bash
# Fresh Docker fixtures only. Never stop/reconfigure any existing application.
set -euo pipefail
if [ "$#" != 1 ] || [ "$(uname -s)" != Linux ]; then
  printf '%s\n' 'Usage: bash scripts/sqlite_container_writer_lab.sh EXISTING_ABSOLUTE_LAB_PARENT' >&2
  exit 2
fi
parent=$1
case "$parent" in /*) :;; *) exit 2;; esac
case "$parent" in *[!a-zA-Z0-9_./-]*) exit 2;; esac
[ -d "$parent" ] && [ "$(readlink -f "$parent")" = "$parent" ]
for dependency in docker readlink mktemp mkdir sha256sum dirname timeout; do
  command -v "$dependency" >/dev/null
done
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
image=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
docker image inspect "$image" >/dev/null
lab=$(mktemp -d "$parent/container-writer.XXXXXX")
mkdir "$lab/media" "$lab/state"
for target in media state; do
  printf 'DISPOSABLE CONTAINER WRITER LAB\n' > "$lab/$target/.disposable_container_writer"
done
printf 'INITIAL\n' > "$lab/media/payload.bin"
printf '0' > "$lab/state/reads"
writer_id=
reader_id=
cleanup(){
  if [ -n "$reader_id" ]; then docker rm -f "$reader_id" >/dev/null 2>&1 || true; fi
  if [ -n "$writer_id" ]; then docker rm -f "$writer_id" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT
create_fixture(){
  docker create --pull=never --network none --read-only --cap-drop ALL --restart no \
    --label media-auditor.disposable-container-writer=true \
    --security-opt no-new-privileges -e PYTHONDONTWRITEBYTECODE=1 \
    --mount "type=bind,src=$repo,dst=/src,readonly" \
    --mount "type=bind,src=$lab/media,dst=/media$1" \
    --mount "type=bind,src=$lab/state,dst=/state" \
    "$image" python -B /src/scripts/sqlite_container_writer_lab.py --role serve
}
check_fixture(){
  timeout --kill-after=5s 15s docker exec "$1" \
    python -B /src/scripts/sqlite_container_writer_lab.py --role "$2"
}
printf '%s\n' 'production_activation=disabled' 'writer_exclusion_verified=false'
printf 'Lab directory: %s\n' "$lab"
writer_id=$(create_fixture '')
docker start "$writer_id" >/dev/null
check_fixture "$writer_id" check-rw
# Quiesce only our newly created writer before creating the read-only service.
docker stop --time 2 "$writer_id" >/dev/null
[ "$(docker inspect --format '{{.State.Running}}' "$writer_id")" = false ]
before=$(sha256sum "$lab/media/payload.bin")
reader_id=$(create_fixture ',readonly')
docker start "$reader_id" >/dev/null
check_fixture "$reader_id" check-ro
[ "$(sha256sum "$lab/media/payload.bin")" = "$before" ]
# Restart only the new read-only fixture; Docker must retain its mount policy.
docker restart --time 2 "$reader_id" >/dev/null
check_fixture "$reader_id" check-ro
[ "$(sha256sum "$lab/media/payload.bin")" = "$before" ]
[ "$(docker inspect --format '{{.State.Running}}' "$writer_id")" = false ]
printf '%s\n' 'media_bytes_unchanged=true' 'stopped_fixture_writer_not_restored=true' \
  'status=isolated_container_write_policy_complete' \
  'Only disposable containers and files were used; no production/NFS configuration was changed.'
