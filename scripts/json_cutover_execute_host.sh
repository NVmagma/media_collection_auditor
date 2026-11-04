#!/usr/bin/env bash
# Explicit fingerprint-bound check/deploy/recovery. No automatic restoration.
set -euo pipefail
umask 077
step=host_preflight
fail() { printf 'status=json_handoff_blocked step=%s reason=%s automatic_restoration=false\n' "$step" "$1" >&2; exit 2; }
trap 'result=$?; printf "status=json_handoff_stopped_for_review step=%s exit_code=%s automatic_restoration=false\n" "$step" "$result" >&2; exit "$result"' ERR
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] && [ "$#" -ge 6 ] && [ "$#" -le 8 ] || fail usage_ACTION_REFERENCE_PREPARATION_REVIEW_BACKUP_BACKUP_SHA_OPTIONAL_REVIEW_SHA_NEW_ID
action=$1 reference=$2 root=$3 review=$4 packet=$5 backup=$6
[[ "$action" = check || "$action" = deploy || "$action" = recover ]] || fail invalid_action
[[ "$reference" =~ ^ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}$ && "$backup" =~ ^[0-9a-f]{64}$ ]] || fail invalid_selection
[ -z "${DOCKER_HOST:-}" ] && [ -z "${DOCKER_CONTEXT:-}" ] || fail docker_override
[ "$(docker context inspect --format '{{.Endpoints.docker.Host}}')" = unix:///var/run/docker.sock ] || fail local_docker_required
for directory in "$root" "$root/logs" "$review" "$packet"; do
  [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" ]] || fail private_path_unavailable
  [ "$(cd -P -- "$directory" && pwd -P)" = "$directory" ] || fail private_path_aliased
done
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
git -c "safe.directory=$checkout" diff --quiet HEAD -- app scripts || fail uncommitted_sources
case "$(git -c "safe.directory=$checkout" branch --show-current)" in feature/interface-api|feature/unraid) ;; *) fail unsupported_branch;; esac
image=$(docker image inspect --format '{{.Id}}' "$reference")
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || fail image_unavailable
[ "$(docker image inspect --format '{{json .Config.Volumes}}' "$image")" = null ] || fail declared_image_volumes
[ "$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.worker"}}' "$image")" = json-serialized ] || fail json_candidate_required
review_sha=$(sha256sum -- "$review/review-complete.json" | cut -d' ' -f1)
if [ "$action" != check ]; then
  [ "$#" -ge 7 ] && [[ "$7" =~ ^[0-9a-f]{64}$ ]] && [ "$7" = "$review_sha" ] || fail explicit_review_fingerprint_required
fi
extra=()
if [ "$#" = 8 ]; then
  [ "$action" = recover ] && [[ "$8" =~ ^[0-9a-f]{64}$ ]] || fail invalid_reviewed_replacement
  extra=(--reviewed-new-id "$8")
fi
review_id=$(stat -Lc '%d:%i' "$review");packet_id=$(stat -Lc '%d:%i' "$packet")
daemon=$(docker info --format '{{.ID}}')
network=none; review_mode=readonly; template_mode=readonly
if [ "$action" != check ]; then network=host;review_mode=readonly=false;template_mode=readonly=false; fi
step=$action
docker run --rm --pull=never --network "$network" --read-only --user 0:0 --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
  --mount type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock \
  --mount "type=bind,src=$root,dst=/prepared,readonly" \
  --mount "type=bind,src=$review,dst=/review,$review_mode" \
  --mount "type=bind,src=$packet,dst=/backup,readonly" \
  --mount "type=bind,src=/boot/config/plugins/dockerMan/templates-user,dst=/templates,$template_mode" \
  --mount "type=bind,src=$checkout,dst=/review-source,readonly" \
  --workdir /app --env PYTHONPATH=/app:/app/app:/review-source --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python "$image" -B -m scripts.json_cutover_execute "$action" \
  --review-identity "$review_id" --review-fingerprint "$review_sha" --backup-identity "$packet_id" \
  --backup-fingerprint "$backup" --daemon-id "$daemon" --host-backup "$packet" --host-checkout "$checkout" "${extra[@]}"
printf 'review_fingerprint=%s\n' "$review_sha"
printf '%s\n' 'automatic_restoration=false'
