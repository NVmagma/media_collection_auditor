#!/usr/bin/env bash
# Build committed bytes; run ONLY a new marked disposable directory/container.
set -euo pipefail
umask 077
[ "$#" = 1 ] || { echo 'Usage: bash SCRIPT EXISTING_DISPOSABLE_LAB_PARENT' >&2; exit 2; }
base=$1
[[ "$base" = /* && ! "$base" =~ [[:cntrl:],] && -d "$base" ]] || exit 2
[ "$(cd -P -- "$base" && pwd -P)" = "$base" ] || { echo 'Canonical existing lab parent required.' >&2; exit 2; }
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
[ "$(git branch --show-current)" = feature/interface-api ] || { echo 'Use feature/interface-api.' >&2; exit 2; }
git diff --quiet HEAD -- app scripts docker unraid/assets requirements.txt || { echo 'Committed runtime and lab sources required.' >&2; exit 2; }
revision=$(git rev-parse --verify HEAD)
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 2
lab=$(mktemp -d "$base/unraid-update.XXXXXX")
printf 'Lab directory: %s\nsource_revision=%s\n' "$lab" "$revision"
printf '%s\n' 'production_activation=disabled' 'production_authorized=false'
mkdir "$lab/source"
git archive --format=tar "$revision" | tar -xf - -C "$lab/source"
printf '%s\n' "$revision" > "$lab/.unraid_update_fixture"
if ! bash scripts/sqlite_preview_release_build.sh > "$lab/image.id" 2> "$lab/build.log"; then
  printf 'status=fixture_build_failed\nBuild diagnostics: %s/build.log\n' "$lab" >&2
  exit 1
fi
image=$(cat "$lab/image.id")
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")" = "$revision" ] || exit 2
volumes=$(docker image inspect --format '{{json .Config.Volumes}}' "$image")
[ "$volumes" = null ] || [ "$volumes" = '{}' ] || exit 2
container=$(docker create --pull=never --network none --read-only --user 0:0 \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=32m \
  --mount "type=bind,src=$lab,dst=/lab" --workdir /app \
  --env PYTHONPATH=/app:/app/app:/lab/source --env PYTHONDONTWRITEBYTECODE=1 \
  --env WEB_SESSION_SECRET=disposable-fixture-session-secret \
  --env "UNRAID_FIXTURE_NONCE=$revision" --env "EXPECTED_REVISION=$revision" \
  --entrypoint python "$image" -B -m scripts.unraid_update_fixture)
[[ "$container" =~ ^[0-9a-f]{64}$ ]] || exit 2
cleanup() { docker rm --force "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker start --attach "$container" 2>&1 | tee "$lab/acceptance.log"
[ "$(docker inspect --format '{{.State.ExitCode}} {{.State.OOMKilled}}' "$container")" = '0 false' ] || exit 1
printf '%s\n' 'status=unraid_update_lab_complete' 'fixture_only=true' \
  'Production containers, templates, appdata and media were not mounted or changed.' \
  'No host ports, Docker socket, NFS controls or kernel changes were used.'
