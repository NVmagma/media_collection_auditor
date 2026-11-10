#!/usr/bin/env bash
# Use the cached runtime and committed source with temporary test mounts only.
set -euo pipefail
umask 077
[ "$#" = 1 ] || { echo 'Usage: bash SCRIPT EXISTING_LAB_PARENT' >&2; exit 2; }
base=$1
[[ "$base" = /* && ! "$base" =~ [[:cntrl:],] && -d "$base" ]] || exit 2
[ "$(cd -P -- "$base" && pwd -P)" = "$base" ] || exit 2
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
revision=$(git rev-parse HEAD)
image=$(docker inspect --format '{{.Image}}' media_collection_auditor)
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
lab=$(mktemp -d "$base/integration-backup.XXXXXX")
mkdir "$lab/source"
git archive "$revision" app scripts/integration_coverage_fixture.py scripts/integration_backup_fixture.py | tar -xf - -C "$lab/source"
printf 'Lab directory: %s\nsource_revision=%s\nfixture_only=true\n' "$lab" "$revision"
container=$(docker create --pull=never --network none --read-only --user "$(id -u):$(id -g)" \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=32m \
  --mount "type=bind,src=$lab,dst=/lab" \
  --mount "type=bind,src=$lab/source,dst=/fixture,readonly" --workdir /fixture \
  --env PYTHONDONTWRITEBYTECODE=1 --env WEB_SESSION_SECRET=synthetic-fixture-secret \
  --env PYTHONPATH=/fixture:/fixture/app --entrypoint python "$image" \
  -B -m scripts.integration_backup_fixture)
trap 'docker rm --force "$container" >/dev/null 2>&1 || true' EXIT
[ "$(docker inspect --format '{{json .Config.Volumes}}' "$container")" = null ] || exit 2
docker start --attach "$container" 2>&1 | tee "$lab/acceptance.log"
[ "$(docker inspect --format '{{.State.ExitCode}} {{.State.OOMKilled}}' "$container")" = '0 false' ] || exit 1
printf '%s\n' 'status=integration_backup_lab_complete' 'production_services_changed=false' \
  'No production media/appdata/socket mounts, published ports, external requests or host controls were used.'
