#!/usr/bin/env bash
# New writable test directories only; no production mounts, ports or Docker socket.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] && [ "$#" = 3 ] || { echo 'Usage: bash SCRIPT CACHED_IMAGE_ID STATE_LAB_PARENT MEDIA_LAB_PARENT' >&2; exit 2; }
image=$1 state_base=$2 media_base=$3
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
for directory in "$state_base" "$media_base"; do
  [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" ]] || exit 2
  [ "$(cd -P -- "$directory" && pwd -P)" = "$directory" ] || exit 2
done
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || exit 2
volumes=$(docker image inspect --format '{{json .Config.Volumes}}' "$image")
[ "$volumes" = null ] || [ "$volumes" = '{}' ] || exit 2
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
git -c "safe.directory=$checkout" diff --quiet HEAD -- app scripts || exit 2
revision=$(git -c "safe.directory=$checkout" rev-parse HEAD)
packaged=false
worker_label=$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.worker"}}' "$image")
if [ "$worker_label" = json-serialized ]; then
  [ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")" = "$revision" ] || exit 2
  packaged=true
fi
state_lab=$(mktemp -d "$state_base/json-worker-state.XXXXXX")
media_lab=$(mktemp -d "$media_base/json-worker-media.XXXXXX")
printf 'State lab directory: %s\nMedia lab directory: %s\nsource_revision=%s\n' "$state_lab" "$media_lab" "$revision"
container=$(docker create --pull=never --network none --read-only --user "$(id -u):$(id -g)" \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 --memory 512m \
  --mount "type=bind,src=$checkout,dst=/review-source,readonly" \
  --mount "type=bind,src=$state_lab,dst=/fixture-state" \
  --mount "type=bind,src=$media_lab,dst=/fixture-media" \
  --workdir /review-source --env PYTHONPATH=/review-source:/app/app --env TZ=UTC \
  --env PYTHONDONTWRITEBYTECODE=1 --env "JSON_FIXTURE_PACKAGED_APP=$packaged" --entrypoint python "$image" -B -m scripts.json_execution_fixture \
  --state-parent /fixture-state --media-parent /fixture-media)
[[ "$container" =~ ^[0-9a-f]{64}$ ]] || exit 2
cleanup() { docker rm --force "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker start --attach "$container"
[ "$(docker inspect --format '{{.State.ExitCode}} {{.State.OOMKilled}}' "$container")" = '0 false' ] || exit 1
printf '%s\n' 'status=json_worker_disposable_lab_complete' 'production_services_changed=false' \
  'Only newly created test directories and a new container were used.'
