#!/usr/bin/env bash
# Check uses read-only data mounts; deploy/recover are explicit single attempts.
set -euo pipefail
umask 077
step=host_preflight
fail() { printf 'status=live_handoff_blocked step=%s reason=%s automatic_restoration=false\n' "$step" "$1" >&2; exit 2; }
trap 'result=$?; printf "status=live_handoff_stopped_for_review step=%s exit_code=%s automatic_restoration=false\n" "$step" "$result" >&2; exit "$result"' ERR
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] && [ "$#" -ge 7 ] && [ "$#" -le 9 ] || fail usage_ACTION_REFERENCE_ROOT_REVIEW_BACKUP_BACKUP_SHA_NATIVE_MEDIA_OPTIONAL_REVIEW_SHA_NEW_ID
action=$1 reference=$2 root=$3 review=$4 packet=$5 backup=$6 native=$7
[[ "$action" = check || "$action" = deploy || "$action" = recover ]] || fail invalid_action
[[ "$reference" =~ ^ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}$ && "$backup" =~ ^[0-9a-f]{64}$ ]] || fail invalid_selection
[ -z "${DOCKER_HOST:-}" ] && [ -z "${DOCKER_CONTEXT:-}" ] || fail docker_override
[ "$(docker context inspect --format '{{.Endpoints.docker.Host}}')" = unix:///var/run/docker.sock ] || fail local_docker_required
for directory in "$root" "$root/logs" "$root/control" "$review" "$packet" "$native"; do
  [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" ]] || fail path_unavailable
  [ "$(cd -P -- "$directory" && pwd -P)" = "$directory" ] || fail aliased_path
done
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
checkout=$PWD
git -c "safe.directory=$checkout" diff --quiet HEAD -- app scripts || fail uncommitted_sources
case "$(git -c "safe.directory=$checkout" branch --show-current)" in feature/interface-api|feature/unraid) ;; *) fail unsupported_branch;; esac
image=$(docker image inspect --format '{{.Id}}' "$reference")
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || fail image_unavailable
[ "$(docker image inspect --format '{{json .Config.Volumes}}' "$image")" = null ] || fail declared_image_volumes
step=original_identity
old_id=$(docker run --rm --pull=never --network none --read-only --cap-drop ALL \
  --mount "type=bind,src=$packet,dst=/packet,readonly" --entrypoint python "$image" -B -c \
  'import json; print(json.load(open("/packet/current.inspect.json"))["Id"])')
[[ "$old_id" =~ ^[0-9a-f]{64}$ ]] || fail original_id_invalid
mounts=$(docker inspect --format '{{range .Mounts}}{{printf "%s %s\n" .Type .Destination}}{{end}}' "$old_id" | sed '/^$/d' | LC_ALL=C sort)
[ "$mounts" = $'bind /app/logs\nbind /media\nbind /sqlite-control' ] || fail original_mounts_changed
mount_source() { docker inspect --format "{{range .Mounts}}{{if eq .Destination \"$1\"}}{{.Source}}{{end}}{{end}}" "$old_id"; }
old_logs=$(mount_source /app/logs);old_control=$(mount_source /sqlite-control);media=$(mount_source /media)
for directory in "$old_logs" "$old_control" "$media"; do
  [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" ]] || fail original_path_unavailable
  [ "$(cd -P -- "$directory" && pwd -P)" = "$directory" ] || fail original_path_aliased
done
review_sha=$(sha256sum -- "$review/review-complete.json" | cut -d' ' -f1)
if [ "$action" != check ]; then
  [ "$#" -ge 8 ] && [[ "$8" =~ ^[0-9a-f]{64}$ ]] && [ "$8" = "$review_sha" ] || fail explicit_review_fingerprint_required
fi
extra=()
if [ "$#" = 9 ]; then
  [ "$action" = recover ] && [[ "$9" =~ ^[0-9a-f]{64}$ ]] || fail invalid_reviewed_replacement
  extra=(--reviewed-new-id "$9")
fi
network=none;review_mode=readonly;template_mode=readonly
if [ "$action" != check ]; then network=host;review_mode=readonly=false;template_mode=readonly=false;fi
review_id=$(stat -Lc '%d:%i' "$review");packet_id=$(stat -Lc '%d:%i' "$packet")
daemon=$(docker info --format '{{.ID}}')
step=$action
docker run --rm --pull=never --network "$network" --read-only --user 0:0 --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
  --mount type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock \
  --mount "type=bind,src=$root/logs,dst=/app/logs,readonly" \
  --mount "type=bind,src=$root/control,dst=/sqlite-control,readonly" \
  --mount "type=bind,src=$old_logs,dst=/old-logs,readonly" \
  --mount "type=bind,src=$old_control,dst=/old-control,readonly" \
  --mount "type=bind,src=$media,dst=/shared-media,readonly" \
  --mount "type=bind,src=$native,dst=/media,readonly" \
  --mount "type=bind,src=$packet,dst=/backup,readonly" \
  --mount "type=bind,src=$review,dst=/review,$review_mode" \
  --mount "type=bind,src=/boot/config/plugins/dockerMan/templates-user,dst=/templates,$template_mode" \
  --mount "type=bind,src=$checkout,dst=/review-source,readonly" \
  --workdir /app --env PYTHONPATH=/app:/app/app:/review-source --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python "$image" -B -m scripts.unraid_live_execute "$action" \
  --review-identity "$review_id" --review-fingerprint "$review_sha" --backup-identity "$packet_id" \
  --backup-fingerprint "$backup" --daemon-id "$daemon" "${extra[@]}"
printf 'review_fingerprint=%s\n' "$review_sha"
printf '%s\n' 'automatic_restoration=false'
