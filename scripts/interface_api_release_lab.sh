#!/usr/bin/env bash
# Exact packaged preview + synthetic HTTP/delivery. Never publish or deploy.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] || { echo 'Run on the Linux Docker host.' >&2; exit 2; }
[ "$#" = 2 ] || { echo 'Usage: bash SCRIPT FULL_PREVIEW_IMAGE_ID EXISTING_LAB_PARENT' >&2; exit 2; }
image=$1
base=$2
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
[[ "$base" = /* && ! "$base" =~ [[:cntrl:],] && -d "$base" ]] || exit 2
[ "$(cd -P -- "$base" && pwd -P)" = "$base" ] || exit 2
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
case "$(git branch --show-current)" in feature/interface-api|feature/unraid) ;; *) exit 2;; esac
git diff --quiet HEAD -- app scripts docker requirements.txt unraid/assets || { echo 'Committed release inputs required.' >&2; exit 2; }
revision=$(git rev-parse HEAD)
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || exit 2
[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")" = "$revision" ] || { echo 'Image must match checkout HEAD.' >&2; exit 2; }
[ "$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.sqlite-activation"}}' "$image")" = preview-only ] || exit 2
[ "$(docker image inspect --format '{{json .Config.Volumes}}' "$image")" = null ] || exit 2
lab=$(mktemp -d "$base/interface-api-release.XXXXXX")
printf 'Lab directory: %s\nsource_revision=%s\nimage_id=%s\n' "$lab" "$revision" "$image"
# Actual process startup and valid/invalid packaged binding are tested first.
bash scripts/sqlite_preview_release_lab.sh "$image" "$lab" | tee "$lab/preview-acceptance.log"
mkdir "$lab/source"
git archive "$revision" scripts | tar -xf - -C "$lab/source"
container=$(docker create --pull=never --network none --read-only --user "$(id -u):$(id -g)" \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 512m \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=32m \
  --mount "type=bind,src=$lab,dst=/lab" \
  --mount "type=bind,src=$lab/source,dst=/fixture,readonly" --workdir /fixture \
  --env PYTHONDONTWRITEBYTECODE=1 --env WEB_SESSION_SECRET=synthetic-release-fixture \
  --env PYTHONPATH=/app:/app/app:/fixture --entrypoint sh "$image" -c \
  'set -eu; python -B -c "import web,app.operational_notifications; from pathlib import Path; assert Path(web.__file__).is_relative_to(\"/app/app\"), \"Packaged application required\""; for module in scripts.integration_coverage_fixture scripts.integration_scans_fixture scripts.integration_backup_fixture scripts.operational_notifications_fixture; do python -B -m "$module"; done')
[[ "$container" =~ ^[0-9a-f]{64}$ ]] || exit 2
trap 'docker rm --force "$container" >/dev/null 2>&1 || true' EXIT
docker start --attach "$container" 2>&1 | tee "$lab/http-delivery-acceptance.log"
[ "$(docker inspect --format '{{.State.ExitCode}} {{.State.OOMKilled}}' "$container")" = '0 false' ] || exit 1
printf '%s\n' 'status=interface_api_release_acceptance_complete' 'fixture_only=true' \
  'production_services_changed=false' 'registry_publication_performed=false' 'media_actions_authorized=false' \
  'Real packaged binding checks and synthetic API/delivery fixtures passed; no production mounts or host ports were used.'
