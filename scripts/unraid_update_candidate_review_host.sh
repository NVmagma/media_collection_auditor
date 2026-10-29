#!/usr/bin/env bash
set -euo pipefail
umask 077
step=preflight
fail() { printf 'status=candidate_review_blocked step=%s reason=%s service_changes_performed=false\n' "$step" "$1" >&2; exit 2; }
trap 'result=$?; printf "status=candidate_review_blocked step=%s reason=command_failed exit_code=%s service_changes_performed=false\n" "$step" "$result" >&2; exit "$result"' ERR
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] && { [ "$#" = 4 ] || [ "$#" = 5 ]; } || fail usage_IMAGE_PREPARED_ROOT_BACKUP_RECEIPT_SHA256
image=$1 root=$2 packet=$3 fingerprint=$4
reference_args=()
if [ "$#" = 5 ]; then
  [[ "$5" =~ ^ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}$ ]] || fail invalid_registry_reference
  [ "$(docker image inspect --format '{{.Id}}' "$5")" = "$image" ] || fail registry_image_mismatch
  reference_args=(--reference "$5")
fi
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ && "$fingerprint" =~ ^[0-9a-f]{64}$ ]] || fail invalid_selection
[ -z "${DOCKER_HOST:-}" ] && [ -z "${DOCKER_CONTEXT:-}" ] || fail docker_context_override
[ "$(docker context inspect --format '{{.Endpoints.docker.Host}}')" = unix:///var/run/docker.sock ] || fail local_docker_endpoint_required
for directory in "$root" "$root/logs" "$root/control" "$packet"; do
  [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" ]] || fail private_path_unavailable
  [ "$(cd -P -- "$directory" && pwd -P)" = "$directory" ] || fail private_path_not_canonical
done
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
checkout=$PWD
git -c "safe.directory=$checkout" diff --quiet HEAD -- app scripts || fail uncommitted_review_sources
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || fail candidate_identity_mismatch
[ "$(docker image inspect --format '{{json .Config.Volumes}}' "$image")" = null ] || fail image_volumes
old_id=$(docker inspect --format '{{.Id}}' media_collection_auditor)
[[ "$old_id" =~ ^[0-9a-f]{64}$ ]] || fail current_identity_invalid
mounts=$(docker inspect --format '{{range .Mounts}}{{printf "%s %s\n" .Type .Destination}}{{end}}' "$old_id" | sed '/^$/d' | LC_ALL=C sort)
[ "$mounts" = $'bind /app/logs\nbind /media\nbind /sqlite-control' ] || fail current_mount_layout_mismatch
source_for() { docker inspect --format "{{range .Mounts}}{{if eq .Destination \"$1\"}}{{.Source}}{{end}}{{end}}" "$old_id"; }
old_logs=$(source_for /app/logs); old_control=$(source_for /sqlite-control); media=$(source_for /media)
for directory in "$old_logs" "$old_control" "$media"; do
  [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" ]] || fail current_path_unavailable
done
signature() { docker inspect --format '{{.Id}} {{json .Config}} {{json .HostConfig}} {{json .Mounts}} {{.State.Running}}' "$old_id" | sha256sum | cut -d' ' -f1; }
before=$(signature)
review=$(mktemp -d "$(dirname -- "$root")/auditor-candidate-review.XXXXXX")
review_id=$(stat -Lc '%d:%i' "$review");packet_id=$(stat -Lc '%d:%i' "$packet")
printf 'New private candidate review: %s\n' "$review"
printf '%s\n' 'Do not paste proposed container/template files; they contain private settings.'
step=private_review
{
  printf '{"containers":';docker inspect "$old_id"
  printf ',"images":';docker image inspect "$image"
  printf '}\n'
} | docker run --rm -i --pull=never --network none --read-only --user 0:0 --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --mount "type=bind,src=$root/logs,dst=/app/logs,readonly" \
  --mount "type=bind,src=$root/control,dst=/sqlite-control,readonly" \
  --mount "type=bind,src=$old_logs,dst=/old-logs,readonly" \
  --mount "type=bind,src=$old_control,dst=/old-control,readonly" \
  --mount "type=bind,src=$media,dst=/media,readonly" \
  --mount "type=bind,src=$packet,dst=/backup,readonly" \
  --mount "type=bind,src=$review,dst=/review" \
  --mount type=bind,src=/boot/config/plugins/dockerMan/templates-user,dst=/templates,readonly \
  --mount "type=bind,src=$checkout,dst=/review-source,readonly" \
  --workdir /app --env PYTHONPATH=/app:/app/app:/review-source --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python "$image" -B -m scripts.unraid_update_candidate_review \
  --backup-identity "$packet_id" --fingerprint "$fingerprint" --output-identity "$review_id" \
  --host-logs "$root/logs" --host-control "$root/control" "${reference_args[@]}"
step=current_container_recheck
[ "$(docker inspect --format '{{.Id}}' media_collection_auditor)" = "$old_id" ] && [ "$(signature)" = "$before" ] || fail current_container_changed
printf '%s\n' 'status=candidate_review_capture_complete' 'service_changes_performed=false' 'template_installed=false' 'deployment_authorized=false'
