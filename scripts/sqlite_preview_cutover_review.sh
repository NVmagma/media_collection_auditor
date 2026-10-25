#!/usr/bin/env bash
# READ-ONLY current-container capture + NEW private files/fixture containers only.
# No stop/start/reload/rename/update/publish/create of a production service.
set -euo pipefail
umask 077
trap 'echo "status=cutover_review_failed production_configuration_changed=false" >&2' ERR
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] || { echo 'Run on Tower as root.' >&2; exit 2; }
[ "$#" = 3 ] || { echo 'Usage: bash SCRIPT PREVIEW_IMAGE_ID EXPECTED_CURRENT_IMAGE_ID EXISTING_PACKET_PARENT' >&2; exit 2; }
image=$1
old_image=$2
base=$3
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ && "$old_image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
[[ "$base" = /* && ! "$base" =~ [[:cntrl:],] && -d "$base" ]] || exit 2
[ "$(cd -P -- "$base" && pwd -P)" = "$base" ] || exit 2
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 2
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || exit 2
[ "$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.sqlite-activation"}}' "$image")" = preview-only ] || exit 2
[ "$(docker image inspect --format '{{.Id}}' "$old_image")" = "$old_image" ] || exit 2
for selected in "$image" "$old_image"; do
  volumes=$(docker image inspect --format '{{json (index .Config "Volumes")}}' "$selected")
  [ "$volumes" = null ] || [ "$volumes" = '{}' ] || exit 2
done
git cat-file -e "$revision:app/sqlite_preview_cutover.py"
git cat-file -e "$revision:scripts/sqlite_preview_capture.py"
observed=$(docker inspect --format '{{.Image}} {{.State.Running}} {{.Id}}' media_collection_auditor)
read -r observed_image running original_id <<< "$observed"
[ "$observed_image" = "$old_image" ] && [ "$running" = true ] && [[ "$original_id" =~ ^[0-9a-f]{64}$ ]] || {
  echo 'Expected running original image/container required; nothing changed.' >&2; exit 2;
}
packet=$(mktemp -d "$base/cutover-review.XXXXXX")
exec {packet_fd}<"$packet"
anchor="/proc/$$/fd/$packet_fd"
printf 'Private review packet: %s\n' "$packet"
printf '%s\n' 'Do not paste private JSON/env/plan files; only the redacted output below.'
docker inspect "$original_id" > "$anchor/original.inspect.json"
for kind in config state; do
  if [ "$kind" = config ]; then raw=original-config.json; meta=config-metadata.json
  else raw=source-observed.json; meta=source-metadata.json; fi
  git show "$revision:scripts/sqlite_preview_capture.py" |
    docker exec --interactive "$original_id" python -B - "$kind" > "$anchor/$raw" 2> "$anchor/$meta"
done
[ "$(docker inspect --format '{{.Image}} {{.State.Running}} {{.Id}}' media_collection_auditor)" = "$observed" ] || exit 1
template=/boot/config/plugins/dockerMan/templates-user/my-media_collection_auditor.xml
if [ -f "$template" ] && [ ! -L "$template" ]; then
  cp -- "$template" "$anchor/original-template.xml"
  chmod 600 "$anchor/original-template.xml"
fi
control_host=/mnt/user/appdata/media_collection_auditor_sqlite_control
if [ -e "$control_host" ] || [ -L "$control_host" ]; then
  echo 'Proposed control destination is occupied; review required. No changes made.' >&2; exit 2;
fi
# The held host-directory descriptor prevents path replacement redirecting capture.
docker run --rm --pull=never --network none --read-only --user 0:0 --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --mount "type=bind,src=$anchor,dst=/packet" --entrypoint python "$image" \
  -B -m app.sqlite_preview_cutover --packet-directory /packet --preview-image "$image" \
  --rollback-image "$old_image" --control-host-path "$control_host"
# Probe the actual cached old image with synthetic JSON in private tmpfs only.
git show "$revision:scripts/sqlite_preview_rollback_probe.py" |
  docker run --rm --pull=never --network none --read-only --user 0:0 --cap-drop ALL \
    --security-opt no-new-privileges --pids-limit 64 --memory 256m \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
    --env WEB_SESSION_SECRET=disposable-rollback-probe-secret --interactive \
    --entrypoint python "$old_image" -B - > "$anchor/rollback-compatibility.json"
printf '%s\n' 'status=cutover_review_capture_complete' 'deployment_authorized=false' \
  'writer_quiescence_verified=false' 'production_configuration_changed=false' \
  'Current auditor, media, configuration, NFS and Docker service state were unchanged.'
