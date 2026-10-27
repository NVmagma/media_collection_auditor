#!/usr/bin/env bash
# Same cached accepted image; prepare new private roots only. Never start/stop.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] && [ "$#" = 3 ] || exit 2
[ -z "${DOCKER_HOST:-}" ] && [ -z "${DOCKER_CONTEXT:-}" ] || exit 2
[ "$(docker context inspect --format '{{.Endpoints.docker.Host}}')" = unix:///var/run/docker.sock ] || exit 2
packet=$1 fingerprint=$2 base=$3
[[ "$fingerprint" =~ ^[0-9a-f]{64}$ ]] || exit 2
for directory in "$packet" "$base"; do
  [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" ]] || exit 2
  [ "$(cd -P -- "$directory" && pwd -P)" = "$directory" ] || exit 2
done
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
git -c "safe.directory=$checkout" diff --quiet HEAD -- app scripts || exit 2
read -r image old_id running reference <<< "$(docker inspect --format '{{.Image}} {{.Id}} {{.State.Running}} {{.Config.Image}}' media_collection_auditor)"
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ && "$old_id" =~ ^[0-9a-f]{64}$ && "$running" = false ]] || exit 2
[[ "$reference" =~ ^ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}$ ]] || exit 2
[ "$(docker image inspect --format '{{.Id}}' "$reference")" = "$image" ] || exit 2
media=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/media"}}{{.Source}}{{end}}{{end}}' "$old_id")
[[ "$media" = /* && ! "$media" =~ [[:cntrl:],] && -d "$media" ]] || exit 2
root=$(mktemp -d "$base/auditor-preview-recovery.XXXXXX")
mkdir -m 700 "$root/logs" "$root/control"
printf 'New private replacement: %s\n' "$root"
printf '%s\n' 'Do not paste runtime.env, template or payload files; only the redacted result.'
packet_id=$(stat -Lc '%d:%i' "$packet")
logs_id=$(stat -Lc '%d:%i' "$root/logs")
control_id=$(stat -Lc '%d:%i' "$root/control")
docker image inspect "$image" | docker run --rm -i --pull=never --network none --read-only --user 0:0 \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --mount "type=bind,src=$packet,dst=/backup,readonly" --mount "type=bind,src=$root/logs,dst=/app/logs" \
  --mount "type=bind,src=$root/control,dst=/sqlite-control" --mount "type=bind,src=$media,dst=/media,readonly" \
  --mount "type=bind,src=$checkout,dst=/review-source,readonly" --workdir /app \
  --env PYTHONPATH=/app:/app/app:/review-source --env PYTHONDONTWRITEBYTECODE=1 --entrypoint python "$image" \
  -B -m scripts.unraid_update_production_prepare --backup /backup --backup-identity "$packet_id" \
  --fingerprint "$fingerprint" --logs-identity "$logs_id" --control-identity "$control_id" \
  --host-logs "$root/logs" --host-control "$root/control" --reference "$reference"
[ "$(docker inspect --format '{{.Id}} {{.State.Running}}' media_collection_auditor)" = "$old_id false" ] || exit 1
printf '%s\n' 'status=replacement_files_ready_not_started' 'production_configuration_changed=false'
