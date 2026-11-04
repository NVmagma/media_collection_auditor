#!/usr/bin/env bash
# Read current packaged authority and write a private two-bind JSON proposal only.
set -euo pipefail
umask 077
step=host_preflight
fail() { printf 'status=json_cutover_review_blocked step=%s reason=%s service_changes_performed=false\n' "$step" "$1" >&2; exit 2; }
trap 'result=$?; printf "status=json_cutover_review_blocked step=%s reason=command_failed exit_code=%s service_changes_performed=false\n" "$step" "$result" >&2; exit "$result"' ERR
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] && [ "$#" = 5 ] || fail usage_IMAGE_PREPARATION_BACKUP_FINGERPRINT_REFERENCE
image=$1 root=$2 packet=$3 fingerprint=$4 reference=$5
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ && "$fingerprint" =~ ^[0-9a-f]{64}$ ]] || fail invalid_selection
[[ "$reference" =~ ^ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}$ ]] || fail invalid_registry_reference
[ -z "${DOCKER_HOST:-}" ] && [ -z "${DOCKER_CONTEXT:-}" ] || fail docker_context_override
[ "$(docker context inspect --format '{{.Endpoints.docker.Host}}')" = unix:///var/run/docker.sock ] || fail local_docker_required
for directory in "$root" "$root/logs" "$packet"; do
  [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" ]] || fail private_path_unavailable
  [ "$(cd -P -- "$directory" && pwd -P)" = "$directory" ] || fail canonical_path_required
done
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
git -c "safe.directory=$checkout" diff --quiet HEAD -- app scripts || fail uncommitted_review_sources
case "$(git -c "safe.directory=$checkout" branch --show-current)" in feature/interface-api|feature/unraid) ;; *) fail unsupported_branch;; esac
[ "$(docker image inspect --format '{{.Id}}' "$reference")" = "$image" ] || fail registry_image_mismatch
[ "$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.worker"}}' "$image")" = json-serialized ] || fail json_candidate_required
old_id=$(docker inspect --format '{{.Id}}' media_collection_auditor)
old_image=$(docker inspect --format '{{.Image}}' "$old_id")
[[ "$old_id" =~ ^[0-9a-f]{64}$ && "$old_image" =~ ^sha256:[0-9a-f]{64}$ ]] || fail current_identity_invalid
[ "$(docker inspect --format '{{.State.Running}}' "$old_id")" = true ] || fail running_original_required
[ "$(docker image inspect --format '{{json .Config.Volumes}}' "$old_image")" = null ] || fail original_declared_volumes
signature() { docker inspect --format '{{.Id}} {{json .Config}} {{json .HostConfig}} {{json .Mounts}} {{.State.Running}}' "$old_id" | sha256sum | cut -d' ' -f1; }
before=$(signature)
packet_id=$(stat -Lc '%d:%i' "$packet")
source_review() {
  docker inspect "$old_id" | docker run --rm -i --pull=never --network none --read-only --user 0:0 \
    --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
    --volumes-from "$old_id:ro" \
    --mount "type=bind,src=$packet,dst=/backup,readonly" \
    --mount "type=bind,src=$checkout,dst=/review-source,readonly" \
    --workdir /app --env PYTHONPATH=/app:/app/app:/review-source --env PYTHONDONTWRITEBYTECODE=1 \
    --entrypoint python "$old_image" -B -m scripts.json_cutover_source_review \
    --backup-identity "$packet_id" --fingerprint "$fingerprint"
}
step=current_source_freshness
source_review
step=private_proposal
review=$(mktemp -d "$(dirname -- "$root")/auditor-json-review.XXXXXX")
review_id=$(stat -Lc '%d:%i' "$review")
printf 'New private JSON review: %s\n' "$review"
printf '%s\n' 'Do not paste proposed container/template files or private preparation contents.'
{
  printf '{"containers":'; docker inspect "$old_id"
  printf ',"images":'; docker image inspect "$image"
  printf '}\n'
} | docker run --rm -i --pull=never --network none --read-only --user 0:0 \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --mount "type=bind,src=$packet,dst=/backup,readonly" \
  --mount "type=bind,src=$root,dst=/prepared,readonly" \
  --mount "type=bind,src=$review,dst=/review" \
  --mount type=bind,src=/boot/config/plugins/dockerMan/templates-user,dst=/templates,readonly \
  --mount "type=bind,src=$checkout,dst=/review-source,readonly" \
  --workdir /app --env PYTHONPATH=/app:/app/app:/review-source --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python "$image" -B -m scripts.json_cutover_review \
  --backup-identity "$packet_id" --fingerprint "$fingerprint" --output-identity "$review_id" \
  --host-logs "$root/logs" --reference "$reference"
step=source_recheck
source_review
[ "$(docker inspect --format '{{.Id}}' media_collection_auditor)" = "$old_id" ] && [ "$(signature)" = "$before" ] || fail original_changed
printf '%s\n' 'status=json_cutover_review_capture_complete' 'service_changes_performed=false' 'template_installed=false' 'deployment_authorized=false'
