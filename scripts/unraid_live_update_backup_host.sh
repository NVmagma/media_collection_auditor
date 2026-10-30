#!/usr/bin/env bash
# Observe the CURRENT live image through RO mounts; write only a new packet.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] && [ "$#" = 1 ] || exit 2
base=$1
[[ "$base" = /* && ! "$base" =~ [[:cntrl:],] && -d "$base" ]] || exit 2
[ "$(cd -P -- "$base" && pwd -P)" = "$base" ] || exit 2
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
git -c "safe.directory=$checkout" diff --quiet HEAD -- app scripts || exit 2
case "$(git -c "safe.directory=$checkout" branch --show-current)" in feature/interface-api|feature/unraid) ;; *) exit 2;; esac
context=${DOCKER_CONTEXT:-$(docker context show)}
endpoint=${DOCKER_HOST:-$(docker context inspect --format '{{(index .Endpoints "docker").Host}}' "$context")}
[[ "$endpoint" = unix:///var/run/docker.sock || "$endpoint" = unix:///run/docker.sock ]] || exit 2
read -r image old_id <<< "$(docker inspect --format '{{.Image}} {{.Id}}' media_collection_auditor)"
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ && "$old_id" =~ ^[0-9a-f]{64}$ ]] || exit 2
[ "$(docker image inspect --format '{{json .Config.Volumes}}' "$image")" = null ] || exit 2
[ "$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.sqlite-activation"}}' "$image")" = scheduled-moves ] || exit 2
mounts=$(docker inspect --format '{{range .Mounts}}{{printf "%s %s\n" .Type .Destination}}{{end}}' "$old_id" | sed '/^$/d' | LC_ALL=C sort)
[ "$mounts" = $'bind /app/logs\nbind /media\nbind /sqlite-control' ] || exit 2
signature() { docker inspect --format '{{.Id}} {{json .Config}} {{json .HostConfig}} {{json .Mounts}} {{.State.Running}}' "$old_id" | sha256sum | cut -d' ' -f1; }
before=$(signature)
packet=$(mktemp -d "$base/auditor-live-update-backup.XXXXXX")
identity=$(stat -Lc '%d:%i' "$packet")
printf 'New private live backup packet: %s\n' "$packet"
printf '%s\n' 'Do not paste private packet contents; only the redacted result.'
docker inspect "$old_id" | docker run --rm -i --pull=never --network none --read-only --user 0:0 \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --volumes-from "$old_id:ro" --mount "type=bind,src=$packet,dst=/update-backup" \
  --mount "type=bind,src=$checkout,dst=/review-source,readonly" \
  --mount type=bind,src=/boot/config/plugins/dockerMan/templates-user,dst=/unraid-templates,readonly \
  --workdir /app --env PYTHONPATH=/app:/app/app --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python "$image" -B -c \
  'import runpy; runpy.run_path("/review-source/scripts/unraid_live_update_backup.py",run_name="__main__")' \
  --directory /update-backup --identity "$identity" --templates /unraid-templates
[ "$(stat -Lc '%d:%i' "$packet")" = "$identity" ] && [ ! -L "$packet" ] || exit 1
[ "$(docker inspect --format '{{.Id}}' media_collection_auditor)" = "$old_id" ] && [ "$(signature)" = "$before" ] || exit 1
printf '%s\n' 'status=current_live_logical_backup_captured' 'production_configuration_changed=false'
