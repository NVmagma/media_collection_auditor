#!/usr/bin/env bash
# Prepare new files only. No production container, template or old data changes.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] && { [ "$#" = 4 ] || [ "$#" = 5 ]; } || {
  echo 'Usage (Tower root): bash SCRIPT PUBLISHED_DIGEST PRIOR_PACKET PRIOR_FINGERPRINT EXISTING_APPDATA_PARENT [empty|restore-previous]' >&2; exit 2;
}
reference=$1 packet=$2 fingerprint=$3 base=$4
tracking_mode=${5:-empty}
[[ "$tracking_mode" = empty || "$tracking_mode" = restore-previous ]] || exit 2
[[ "$reference" =~ ^ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}$ && "$fingerprint" =~ ^[0-9a-f]{64}$ ]] || exit 2
for directory in "$packet" "$base"; do
  [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" && ! -L "$directory" ]] || exit 2
  [ "$(cd -P -- "$directory" && pwd -P)" = "$directory" ] || exit 2
done
[ "$(stat -Lc '%u:%a' "$packet")" = 0:700 ] || exit 2
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
git_cmd=(git -c "safe.directory=$checkout")
case "$("${git_cmd[@]}" branch --show-current)" in
  feature/sqlite|feature/unraid|feature/interface-api) ;;
  *) exit 2;;
esac
revision=$("${git_cmd[@]}" rev-parse HEAD)
"${git_cmd[@]}" diff --quiet HEAD -- app scripts || exit 2
if [ -n "${DOCKER_CONTEXT:-}" ]; then
  endpoint=$(docker context inspect --format '{{(index .Endpoints "docker").Host}}' "$DOCKER_CONTEXT")
elif [ -n "${DOCKER_HOST:-}" ]; then endpoint=$DOCKER_HOST
else endpoint=$(docker context inspect --format '{{(index .Endpoints "docker").Host}}' "$(docker context show)"); fi
[[ "$endpoint" = unix:///var/run/docker.sock || "$endpoint" = unix:///run/docker.sock ]] || exit 2
image=$(docker image inspect --format '{{.Id}}' "$reference")
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")" = "$revision" ] || exit 2
[ "$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.sqlite-activation"}}' "$image")" = preview-only ] || exit 2
exec {packet_fd}<"$packet"
packet_identity=$(stat -Lc '%d:%i' "/proc/$$/fd/$packet_fd")
root=$(mktemp -d "$base/media_collection_auditor_fresh.XXXXXX")
printf 'Fresh private directory: %s\n' "$root"
trap 'echo "status=fresh_preparation_stopped_for_review existing_services_changed=false partial_files_retained=true" >&2' ERR
mkdir -m 700 -- "$root/logs" "$root/control"
logs_identity=$(stat -Lc '%d:%i' "$root/logs")
control_identity=$(stat -Lc '%d:%i' "$root/control")
"${git_cmd[@]}" archive --format=tar "$revision" scripts |
  docker run --rm --pull=never --network none --read-only --user 0:0 --cap-drop ALL \
    --security-opt no-new-privileges --pids-limit 64 --memory 256m \
    --tmpfs /tools:rw,noexec,nosuid,nodev,size=32m,mode=0700 \
    --mount "type=bind,src=$packet,dst=/packet,readonly" \
    --mount "type=bind,src=$root/logs,dst=/app/logs" \
    --mount "type=bind,src=$root/control,dst=/sqlite-control" \
    --mount type=bind,src=/mnt/user/media_storage,dst=/media,readonly \
    --env PYTHONPATH=/tools:/app:/app/app --interactive --workdir /tools --entrypoint python "$image" -B -c \
    'import io,sys,tarfile,subprocess; tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode="r:").extractall("/tools",filter="data"); subprocess.run([sys.executable,"-B","-m","scripts.sqlite_preview_fresh",*sys.argv[1:]],check=True)' \
    --packet /packet --packet-identity "$packet_identity" --fingerprint "$fingerprint" \
    --logs-identity "$logs_identity" --control-identity "$control_identity" \
    --host-logs "$root/logs" --host-control "$root/control" --image-id "$image" --reference "$reference" \
    --tracking-mode "$tracking_mode"
[ ! -L "$packet" ] && [ "$(stat -Lc '%d:%i' "$packet")" = "$packet_identity" ] || exit 1
printf '%s\n' 'status=fresh_sqlite_files_ready_not_started' 'existing_services_changed=false' \
  'Old appdata, SQLite state, rollback containers and Unraid templates were not changed.' \
  'Do not paste runtime.env, private settings or template contents.'
