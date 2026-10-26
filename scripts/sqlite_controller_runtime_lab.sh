#!/bin/bash
# NEW disposable runtime only. No existing service is stopped or configured.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] || { echo 'Run on the Linux host, not macOS.' >&2; exit 1; }
[ "$(id -u)" = 0 ] || { echo 'Root required for the new disposable chroot.' >&2; exit 1; }
[ "$#" = 1 ] || { echo 'Usage: bash scripts/sqlite_controller_runtime_lab.sh EXISTING_LAB_BASE' >&2; exit 1; }
for tool in docker chroot unshare realpath mktemp env; do command -v "$tool" >/dev/null; done
base=$(realpath -e -- "$1")
[ -d "$base" ]
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
image=${SQLITE_LAB_IMAGE:-python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1}
[[ "$image" =~ ^([A-Za-z0-9._:/-]+@sha256:|sha256:)[0-9a-f]{64}$ ]] || { echo "Immutable reviewed image digest required." >&2; exit 1; }
# Cached reviewed image only: no pull, build, dependency install or network.
docker image inspect "$image" >/dev/null
lab=$(mktemp -d -- "$base/controller-runtime.XXXXXX")
printf 'DISPOSABLE CONTROLLER RUNTIME ONLY\n' > "$lab/.disposable_controller_runtime"
printf 'Lab directory: %s\n' "$lab"
container_id=
cleanup() {
  if [[ "$container_id" =~ ^[0-9a-f]{64}$ ]]; then
    docker rm "$container_id" >/dev/null || true
  fi
}
trap cleanup EXIT
# This new container is never started and has no host bind mounts.
container_id=$(docker create --pull=never --network none --read-only --entrypoint /bin/true "$image")
[[ "$container_id" =~ ^[0-9a-f]{64}$ ]]
docker export --output "$lab/image.tar" "$container_id"
docker run --rm --pull=never --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 512m \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --mount "type=bind,src=$source_dir/sqlite_controller_runtime_prepare.py,dst=/prepare.py,readonly" \
  --mount "type=bind,src=$lab,dst=/lab" \
  --entrypoint /usr/local/bin/python3 "$image" -I -B /prepare.py --root /lab
# Launched by the HOST, not docker exec/run. This fixed smoke program touches
# only /tmp in the new rootfs. No host /proc, /dev, media, settings or sockets
# are mounted into it. A new network namespace has no production interfaces.
env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin unshare --net -- chroot "$lab/rootfs" /usr/local/bin/python3 -I -B /controller-smoke.py
printf 'Production services/configuration unchanged; runtime artifacts retained.\n'
