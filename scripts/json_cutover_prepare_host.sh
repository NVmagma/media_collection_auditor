#!/usr/bin/env bash
# Write only a new private JSON preparation; never stop/start/edit production.
set -euo pipefail
umask 077
step=host_preflight
fail() { printf 'status=json_preparation_blocked step=%s reason=%s production_configuration_changed=false\n' "$step" "$1" >&2; exit 2; }
trap 'result=$?; printf "status=json_preparation_blocked step=%s reason=command_failed exit_code=%s production_configuration_changed=false\n" "$step" "$result" >&2; exit "$result"' ERR
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] && [ "$#" = 4 ] || {
  echo 'Usage: bash SCRIPT CACHED_JSON_IMAGE_ID BACKUP_PACKET FINGERPRINT PRIVATE_PARENT' >&2; exit 2;
}
image=$1 packet=$2 fingerprint=$3 base=$4
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ && "$fingerprint" =~ ^[0-9a-f]{64}$ ]] || fail invalid_selection_format
[ -z "${DOCKER_HOST:-}" ] && [ -z "${DOCKER_CONTEXT:-}" ] || fail docker_context_override_requires_review
[ "$(docker context inspect --format '{{.Endpoints.docker.Host}}')" = unix:///var/run/docker.sock ] || fail local_docker_endpoint_required
for directory in "$packet" "$base"; do
  [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" ]] || fail private_directory_unavailable
  [ "$(cd -P -- "$directory" && pwd -P)" = "$directory" ] || fail private_directory_not_canonical
done
step=source_preflight
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
git -c "safe.directory=$checkout" diff --quiet HEAD -- app scripts || fail uncommitted_preparation_sources
case "$(git -c "safe.directory=$checkout" branch --show-current)" in feature/interface-api|feature/unraid) ;; *) fail unsupported_source_branch;; esac
revision=$(git -c "safe.directory=$checkout" rev-parse HEAD)
step=candidate_preflight
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || fail candidate_image_identity_mismatch
[ "$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.worker"}}' "$image")" = json-serialized ] || fail json_candidate_required
[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")" = "$revision" ] || fail candidate_revision_mismatch
[ "$(docker image inspect --format '{{json .Config.Volumes}}' "$image")" = null ] || fail candidate_declared_volumes_require_review
step=current_container_preflight
old_id=$(docker inspect --format '{{.Id}}' media_collection_auditor)
[[ "$old_id" =~ ^[0-9a-f]{64}$ ]] || fail current_container_identity_invalid
signature() { docker inspect --format '{{.Id}} {{json .Config}} {{json .HostConfig}} {{json .Mounts}} {{.State.Running}}' "$old_id" | sha256sum | cut -d' ' -f1; }
before=$(signature)
while IFS= read -r source; do
  [ -n "$source" ] || continue
  [ "$source" != / ] || fail preparation_parent_overlaps_current_bind
  case "$base" in "$source"|"$source"/*) fail preparation_parent_overlaps_current_bind;; esac
done < <(docker inspect --format '{{range .Mounts}}{{printf "%s\n" .Source}}{{end}}' "$old_id")
step=new_private_root
root=$(mktemp -d "$base/auditor-json-preparation.XXXXXX")
packet_id=$(stat -Lc '%d:%i' "$packet"); root_id=$(stat -Lc '%d:%i' "$root")
printf 'New private JSON preparation: %s\n' "$root"
printf '%s\n' 'Do not paste runtime.env, private configuration, source tracking or claim archive contents.'
step=prepare_json_files
docker image inspect "$image" | docker run --rm -i --pull=never --network none --read-only --user 0:0 \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --mount "type=bind,src=$packet,dst=/backup,readonly" \
  --mount "type=bind,src=$root,dst=/json-preparation" \
  --mount "type=bind,src=$checkout,dst=/review-source,readonly" \
  --workdir /app --env PYTHONPATH=/app:/app/app:/review-source --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python "$image" -B -m scripts.json_cutover_prepare \
  --backup /backup --backup-identity "$packet_id" --fingerprint "$fingerprint" \
  --root /json-preparation --root-identity "$root_id" --revision "$revision" --original-container-id "$old_id"
step=verify_original
[ "$(stat -Lc '%d:%i' "$root")" = "$root_id" ] && [ ! -L "$root" ] || fail preparation_root_changed
[ "$(docker inspect --format '{{.Id}}' media_collection_auditor)" = "$old_id" ] && [ "$(signature)" = "$before" ] || fail current_container_changed
printf '%s\n' 'status=json_replacement_files_ready_not_started' 'production_configuration_changed=false' \
  'template_installed=false' 'deployment_authorized=false'
