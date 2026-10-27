#!/usr/bin/env bash
# Synthetic, expiring UI server only; never starts the auditor worker.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] || { echo 'Run on Tower / the Linux Docker host.' >&2; exit 2; }
[ "$#" -ge 1 ] && [ "$#" -le 2 ] || { echo 'Usage: bash SCRIPT EXISTING_LAB_PARENT [HOST_PORT=8091]' >&2; exit 2; }
base=$1
port=${2:-8091}
[[ "$base" = /* && ! "$base" =~ [[:cntrl:],] && -d "$base" ]] || exit 2
[ "$(cd -P -- "$base" && pwd -P)" = "$base" ] || exit 2
[[ "$port" =~ ^[1-9][0-9]{3,4}$ ]] && [ "$port" -ge 1024 ] && [ "$port" -le 65535 ] || exit 2
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
revision=$(git rev-parse HEAD)
image=$(docker inspect --format '{{.Image}}' media_collection_auditor)
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
docker image inspect "$image" >/dev/null
lab=$(mktemp -d "$base/dashboard-workspace.XXXXXX")
mkdir "$lab/source"
git archive "$revision" app tests/dashboard_workspace_case.py tests/settings_workspace_case.py scripts/dashboard_workspace_server.py unraid/assets |
  tar -xf - -C "$lab/source"
container=$(docker create --pull=never --network bridge --read-only --user "$(id -u):$(id -g)" \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777 \
  --publish "$port:8080" --mount "type=bind,src=$lab/source,dst=/fixture,readonly" \
  --env PYTHONDONTWRITEBYTECODE=1 --env WEB_SESSION_SECRET=synthetic-disposable-preview \
  --env PYTHONPATH=/fixture:/fixture/app:/fixture/tests --workdir /fixture \
  --entrypoint python "$image" -B -m scripts.dashboard_workspace_server --lifetime-seconds 900)
cleanup_failed() { docker rm --force "$container" >/dev/null 2>&1 || true; }
trap cleanup_failed ERR
[ "$(docker inspect --format '{{json .Config.Volumes}}' "$container")" = null ] || {
  echo 'Unexpected inherited image volumes; fixture removed.' >&2; cleanup_failed; exit 2;
}
docker start "$container" >/dev/null
for attempt in $(seq 1 30); do
  if curl --noproxy '*' --max-time 2 --fail --silent "http://127.0.0.1:$port/" > "$lab/preview.html"; then
    printf 'dashboard_fixture_ready=true\nfixture_only=true\nsource_revision=%s\nlab_directory=%s\ncontainer_id=%s\npreview_url=http://10.0.0.10:%s\nlifetime_seconds=900\nproduction_services_changed=false\n' "$revision" "$lab" "$container" "$port"
    printf '%s\n' 'Synthetic dashboard only; no media/appdata/socket mounts. The new container stops after 15 minutes.'
    trap - ERR
    exit 0
  fi
  [ "$(docker inspect --format '{{.State.Running}}' "$container")" = true ] || break
  sleep 1
done
docker logs "$container" > "$lab/startup.log" 2>&1
cleanup_failed
printf 'status=fixture_start_failed\nfixture_log=%s/startup.log\n' "$lab"
exit 1
