#!/usr/bin/env bash
# Read the existing preview through read-only inherited mounts; write only a
# new private backup packet. Never stop/start/rename or install a template.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] && { [ "$#" = 1 ] || [ "$#" = 2 ]; } || {
  echo 'Usage (Tower root): bash SCRIPT EXISTING_PRIVATE_BACKUP_PARENT' >&2; exit 2;
}
base=$1
mode=${2:-current}
[[ "$mode" = current || "$mode" = enable-tv-preview ]] || exit 2
[[ "$base" = /* && ! "$base" =~ [[:cntrl:],] && -d "$base" ]] || exit 2
[ "$(cd -P -- "$base" && pwd -P)" = "$base" ] || exit 2
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
git_cmd=(git -c "safe.directory=$checkout")
"${git_cmd[@]}" diff --quiet HEAD -- app scripts || { echo 'Committed capture code required.' >&2; exit 2; }
case "$("${git_cmd[@]}" branch --show-current)" in feature/interface-api|feature/unraid) ;; *) exit 2;; esac
if [ -n "${DOCKER_CONTEXT:-}" ]; then context=$DOCKER_CONTEXT; else context=$(docker context show); fi
endpoint=${DOCKER_HOST:-$(docker context inspect --format '{{(index .Endpoints "docker").Host}}' "$context")}
[[ "$endpoint" = unix:///var/run/docker.sock || "$endpoint" = unix:///run/docker.sock ]] || {
  echo 'Local Tower Docker context required.' >&2; exit 2;
}
read -r image old_id <<< "$(docker inspect --format '{{.Image}} {{.Id}}' media_collection_auditor)"
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ && "$old_id" =~ ^[0-9a-f]{64}$ ]] || exit 2
volumes=$(docker image inspect --format '{{json .Config.Volumes}}' "$image")
[ "$volumes" = null ] || [ "$volumes" = '{}' ] || exit 2
mounts=$(docker inspect --format '{{range .Mounts}}{{printf "%s %s\n" .Type .Destination}}{{end}}' "$old_id" | sed '/^$/d' | LC_ALL=C sort)
[ "$mounts" = $'bind /app/logs\nbind /media\nbind /sqlite-control' ] || exit 2
extra_mounts=()
extra_args=()
if [ "$mode" = enable-tv-preview ]; then
  [ "$(docker inspect --format '{{.State.Running}}' "$old_id")" = false ] || exit 2
  control_source=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/sqlite-control"}}{{.Source}}{{end}}{{end}}' "$old_id")
  logs_source=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/logs"}}{{.Source}}{{end}}{{end}}' "$old_id")
  for directory in "$control_source" "$logs_source"; do
    [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" ]] || exit 2
    [ "$(cd -P -- "$directory" && pwd -P)" = "$directory" ] || exit 2
  done
  for file in "$control_source/preview-config.json" "$logs_source/auditor_config.json"; do
    [ -f "$file" ] && [ ! -L "$file" ] || exit 2
  done
  extra_mounts+=(--mount "type=bind,src=$control_source/preview-config.json,dst=/app/logs/auditor_config.json,readonly")
  extra_mounts+=(--mount "type=bind,src=$logs_source/auditor_config.json,dst=/selected-settings.json,readonly")
  extra_args+=(--selected-settings /selected-settings.json)
fi
packet=$(mktemp -d "$base/auditor-update-backup.XXXXXX")
exec {packet_fd}<"$packet"
identity=$(stat -Lc '%d:%i' "/proc/$$/fd/$packet_fd")
printf 'New private backup packet: %s\n' "$packet"
printf '%s\n' 'Do not paste private packet contents; only the redacted result.'
docker inspect "$old_id" | docker run --rm -i --pull=never --network none --read-only --user 0:0 \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --volumes-from "$old_id:ro" "${extra_mounts[@]}" --mount "type=bind,src=$packet,dst=/update-backup" \
  --mount "type=bind,src=$checkout,dst=/review-source,readonly" \
  --mount type=bind,src=/boot/config/plugins/dockerMan/templates-user,dst=/unraid-templates,readonly \
  --workdir /app --env PYTHONPATH=/app:/app/app:/review-source --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python "$image" -B -m scripts.unraid_update_backup \
  --directory /update-backup --identity "$identity" --templates /unraid-templates "${extra_args[@]}"
[ "$(stat -Lc '%d:%i' "$packet")" = "$identity" ] && [ ! -L "$packet" ] || exit 1
[ "$(docker inspect --format '{{.Id}}' media_collection_auditor)" = "$old_id" ] || exit 1
printf '%s\n' 'status=current_preview_logical_backup_captured' 'production_configuration_changed=false'
