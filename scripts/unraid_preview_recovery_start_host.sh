#!/usr/bin/env bash
# Explicit selected recovery; original container is retained, never removed.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] && [ "$#" = 4 ] || exit 2
[ -z "${DOCKER_HOST:-}" ] && [ -z "${DOCKER_CONTEXT:-}" ] || exit 2
[ "$(docker context inspect --format '{{.Endpoints.docker.Host}}')" = unix:///var/run/docker.sock ] || exit 2
root=$1 selection=$2 packet=$3 backup=$4
[[ "$selection" =~ ^[0-9a-f]{64}$ && "$backup" =~ ^[0-9a-f]{64}$ ]] || exit 2
for directory in "$root" "$root/logs" "$root/control" "$packet"; do
  [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" ]] || exit 2
  [ "$(cd -P -- "$directory" && pwd -P)" = "$directory" ] || exit 2
done
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
git -c "safe.directory=$checkout" diff --quiet HEAD -- app scripts || exit 2
read -r image old_id running <<< "$(docker inspect --format '{{.Image}} {{.Id}} {{.State.Running}}' media_collection_auditor)"
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ && "$old_id" =~ ^[0-9a-f]{64}$ && "$running" = false ]] || exit 2
mount_source() { docker inspect --format "{{range .Mounts}}{{if eq .Destination \"$1\"}}{{.Source}}{{end}}{{end}}" "$old_id"; }
old_logs=$(mount_source /app/logs)
old_control=$(mount_source /sqlite-control)
media=$(mount_source /media)
for directory in "$old_logs" "$old_control" "$media"; do
  [[ "$directory" = /* && ! "$directory" =~ [[:cntrl:],] && -d "$directory" ]] || exit 2
done
[ -f /boot/config/plugins/dockerMan/templates-user/my-media_collection_auditor.xml ] || exit 2
daemon=$(docker info --format '{{.ID}}')
logs_id=$(stat -Lc '%d:%i' "$root/logs")
packet_id=$(stat -Lc '%d:%i' "$packet")
docker run --rm --pull=never --network host --read-only --user 0:0 --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --mount type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock \
  --mount "type=bind,src=$root/logs,dst=/app/logs" \
  --mount "type=bind,src=$root/control,dst=/sqlite-control,readonly" \
  --mount "type=bind,src=$old_logs,dst=/old-logs,readonly" \
  --mount "type=bind,src=$old_control,dst=/old-control,readonly" \
  --mount "type=bind,src=$media,dst=/media,readonly" \
  --mount "type=bind,src=$packet,dst=/backup,readonly" \
  --mount type=bind,src=/boot/config/plugins/dockerMan/templates-user,dst=/templates \
  --mount "type=bind,src=$checkout,dst=/review-source,readonly" \
  --workdir /app --env PYTHONPATH=/app:/app/app:/review-source --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python "$image" -B -m scripts.unraid_preview_recovery_start \
  --selection-fingerprint "$selection" --backup-fingerprint "$backup" --daemon-id "$daemon" \
  --logs-identity "$logs_id" --backup-identity "$packet_id"
