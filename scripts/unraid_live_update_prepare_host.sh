#!/usr/bin/env bash
# New roots/binding only. No production stop/start/template or registry commands.
set -euo pipefail
umask 077
step=host_preflight
fail() {
  printf 'status=live_preparation_blocked step=%s reason=%s production_configuration_changed=false\n' "$step" "$1" >&2
  exit 2
}
trap 'result=$?; printf "status=live_preparation_blocked step=%s reason=command_failed exit_code=%s production_configuration_changed=false\n" "$step" "$result" >&2; exit "$result"' ERR
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] && { [ "$#" = 5 ] || { [ "$#" = 6 ] && [ "$6" = --library-slots ]; }; } || { echo 'Usage: bash SCRIPT CANDIDATE_IMAGE_ID BACKUP_PACKET RECEIPT_SHA256 PRIVATE_PARENT NATIVE_MEDIA_ROOT [--library-slots]' >&2; exit 2; }
[ -z "${DOCKER_HOST:-}" ] && [ -z "${DOCKER_CONTEXT:-}" ] || fail docker_context_override_requires_review
[ "$(docker context inspect --format '{{.Endpoints.docker.Host}}')" = unix:///var/run/docker.sock ] || fail local_docker_endpoint_required
image=$1 packet=$2 fingerprint=$3 base=$4 media=$5
slot_args=()
if [ "$#" = 6 ]; then slot_args=(--library-slots); fi
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ && "$fingerprint" =~ ^[0-9a-f]{64}$ ]] || fail selection_format_invalid
for directory in "$packet" "$base"; do
  [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" ]] || fail private_path_unavailable
  [ "$(cd -P -- "$directory" && pwd -P)" = "$directory" ] || fail private_path_not_canonical
done
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
checkout=$PWD
step=source_preflight
git -c "safe.directory=$checkout" diff --quiet HEAD -- app scripts || fail uncommitted_preparation_sources
case "$(git -c "safe.directory=$checkout" branch --show-current)" in feature/interface-api|feature/unraid) ;; *) fail unsupported_source_branch;; esac
step=candidate_preflight
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || fail candidate_image_identity_mismatch
[ "$(docker image inspect --format '{{json .Config.Volumes}}' "$image")" = null ] || fail candidate_declared_volumes_require_review
[ "$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.sqlite-activation"}}' "$image")" = scheduled-moves ] || fail candidate_live_profile_required
step=current_container_preflight
old_id=$(docker inspect --format '{{.Id}}' media_collection_auditor)
[[ "$old_id" =~ ^[0-9a-f]{64}$ ]] || fail current_container_identity_invalid
mounts=$(docker inspect --format '{{range .Mounts}}{{printf "%s %s\n" .Type .Destination}}{{end}}' "$old_id" | sed '/^$/d' | LC_ALL=C sort)
[ "$mounts" = $'bind /app/logs\nbind /media\nbind /sqlite-control' ] || fail current_mount_layout_mismatch
[ "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/media"}}{{.RW}}{{end}}{{end}}' "$old_id")" = true ] || fail current_live_media_not_writable
[[ "$media" = /* && ! "$media" =~ [[:cntrl:],] && -d "$media" ]] || fail media_path_unavailable
[ "$(cd -P -- "$media" && pwd -P)" = "$media" ] || fail media_path_not_canonical
filesystem=$(findmnt -n -T "$media" -o FSTYPE)
case "$filesystem" in btrfs|xfs|ext4|zfs) ;; *) fail native_filesystem_required;; esac
current_media=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/media"}}{{.Source}}{{end}}{{end}}' "$old_id")
[ "$current_media" = "$media" ] || fail current_native_media_binding_mismatch
step=new_private_roots
root=$(mktemp -d "$base/auditor-live-update-preparation.XXXXXX")
mkdir -m 700 "$root/logs" "$root/control"
printf 'New private live update preparation: %s\n' "$root"
printf '%s\n' 'Do not paste runtime.env, private settings, source snapshots or binding files.'
packet_id=$(stat -Lc '%d:%i' "$packet")
logs_id=$(stat -Lc '%d:%i' "$root/logs")
control_id=$(stat -Lc '%d:%i' "$root/control")
step=prepare_candidate_files
docker image inspect "$image" | docker run --rm -i --pull=never --network none --read-only --user 0:0 \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --mount "type=bind,src=$packet,dst=/backup,readonly" \
  --mount "type=bind,src=$root/logs,dst=/app/logs" --mount "type=bind,src=$root/control,dst=/sqlite-control" \
  --mount "type=bind,src=$media,dst=/media,readonly" \
  --mount "type=bind,src=$checkout,dst=/review-source,readonly" --workdir /app \
  --env PYTHONPATH=/app:/app/app:/review-source --env PYTHONDONTWRITEBYTECODE=1 --entrypoint python "$image" \
  -B -m scripts.unraid_live_prepare --live-update --image-id "$image" --backup /backup \
  --backup-identity "$packet_id" --fingerprint "$fingerprint" --logs /app/logs --logs-identity "$logs_id" \
  --control /sqlite-control --control-identity "$control_id" "${slot_args[@]}"
step=verify_original_container
[ "$(docker inspect --format '{{.Id}}' media_collection_auditor)" = "$old_id" ] || fail current_container_replaced
printf '%s\n' 'status=live_update_files_ready_not_started' 'production_configuration_changed=false' \
  'registry_reference_configured=false' 'container_payload_prepared=false' 'deployment_authorized=false'
