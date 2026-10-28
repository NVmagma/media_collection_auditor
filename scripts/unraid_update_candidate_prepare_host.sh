#!/usr/bin/env bash
# New roots/binding only. No production stop/start/template or registry commands.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] && [ "$#" = 4 ] || { echo 'Usage: bash SCRIPT CANDIDATE_IMAGE_ID BACKUP_PACKET RECEIPT_SHA256 PRIVATE_PARENT' >&2; exit 2; }
[ -z "${DOCKER_HOST:-}" ] && [ -z "${DOCKER_CONTEXT:-}" ] || exit 2
[ "$(docker context inspect --format '{{.Endpoints.docker.Host}}')" = unix:///var/run/docker.sock ] || exit 2
image=$1 packet=$2 fingerprint=$3 base=$4
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ && "$fingerprint" =~ ^[0-9a-f]{64}$ ]] || exit 2
for directory in "$packet" "$base"; do
  [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" ]] || exit 2
  [ "$(cd -P -- "$directory" && pwd -P)" = "$directory" ] || exit 2
done
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
checkout=$PWD
git -c "safe.directory=$checkout" diff --quiet HEAD -- app scripts || exit 2
case "$(git -c "safe.directory=$checkout" branch --show-current)" in feature/interface-api|feature/unraid) ;; *) exit 2;; esac
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || exit 2
[ "$(docker image inspect --format '{{json .Config.Volumes}}' "$image")" = null ] || exit 2
[ "$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.sqlite-activation"}}' "$image")" = preview-only ] || exit 2
old_id=$(docker inspect --format '{{.Id}}' media_collection_auditor)
[[ "$old_id" =~ ^[0-9a-f]{64}$ ]] || exit 2
mounts=$(docker inspect --format '{{range .Mounts}}{{printf "%s %s\n" .Type .Destination}}{{end}}' "$old_id" | LC_ALL=C sort)
[ "$mounts" = $'bind /app/logs\nbind /media\nbind /sqlite-control' ] || exit 2
[ "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/media"}}{{.RW}}{{end}}{{end}}' "$old_id")" = false ] || exit 2
media=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/media"}}{{.Source}}{{end}}{{end}}' "$old_id")
[[ "$media" = /* && ! "$media" =~ [[:cntrl:],] && -d "$media" ]] || exit 2
[ "$(cd -P -- "$media" && pwd -P)" = "$media" ] || exit 2
root=$(mktemp -d "$base/auditor-candidate-preparation.XXXXXX")
mkdir -m 700 "$root/logs" "$root/control"
printf 'New private candidate roots: %s\n' "$root"
printf '%s\n' 'Do not paste runtime.env, private settings, source snapshots or binding files.'
packet_id=$(stat -Lc '%d:%i' "$packet")
logs_id=$(stat -Lc '%d:%i' "$root/logs")
control_id=$(stat -Lc '%d:%i' "$root/control")
docker image inspect "$image" | docker run --rm -i --pull=never --network none --read-only --user 0:0 \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --mount "type=bind,src=$packet,dst=/backup,readonly" \
  --mount "type=bind,src=$root/logs,dst=/app/logs" --mount "type=bind,src=$root/control,dst=/sqlite-control" \
  --mount "type=bind,src=$media,dst=/media,readonly" \
  --mount "type=bind,src=$checkout,dst=/review-source,readonly" --workdir /app \
  --env PYTHONPATH=/app:/app/app:/review-source --env PYTHONDONTWRITEBYTECODE=1 --entrypoint python "$image" \
  -B -m scripts.unraid_update_candidate_prepare --image-id "$image" --backup /backup \
  --backup-identity "$packet_id" --fingerprint "$fingerprint" --logs /app/logs --logs-identity "$logs_id" \
  --control /sqlite-control --control-identity "$control_id"
[ "$(docker inspect --format '{{.Id}}' media_collection_auditor)" = "$old_id" ] || exit 1
printf '%s\n' 'status=candidate_files_ready_not_started' 'production_configuration_changed=false' \
  'registry_reference_configured=false' 'container_payload_prepared=false' 'deployment_authorized=false'
