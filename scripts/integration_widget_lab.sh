#!/bin/bash
# Starts only a new, expiring synthetic API container. No production mounts.
set -eu
umask 077
if [ "$#" -gt 1 ]; then
  printf '%s\n' 'Usage: bash scripts/integration_widget_lab.sh [sample|titles|empty|unavailable]' >&2
  exit 2
fi
scenario=${1:-sample}
case "$scenario" in sample|titles|empty|unavailable) ;; *) exit 2 ;; esac
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
[ "$(docker network inspect bridge --format '{{.Driver}}')" = bridge ]
icc=$(docker network inspect bridge --format '{{index .Options "com.docker.network.bridge.enable_icc"}}')
if [ "$icc" = false ]; then
  printf '%s\n' 'blocked: bridge container communication disabled; no changes made' >&2
  exit 2
fi
for dashboard in homepage homarr; do
  [ "$(docker inspect --type container --format '{{with index .NetworkSettings.Networks "bridge"}}bridge{{end}}' "$dashboard")" = bridge ]
done
image_id=$(docker inspect --type container --format '{{.Image}}' media_collection_auditor)
lab_directory=$(mktemp -d /tmp/auditor-widget.XXXXXX)
lab_name="auditor-widget-${lab_directory##*.}"
container_id=''
cleanup_failure() {
  if [ -n "$container_id" ]; then
    observed=$(docker inspect --type container --format '{{index .Config.Labels "org.nvmagma.auditor.fixture"}}' "$container_id" 2>/dev/null || true)
    if [ "$observed" = widget-api ]; then
      docker stop --time 5 "$container_id" >/dev/null 2>&1 || true
    fi
  fi
}
trap cleanup_failure EXIT
# Generate a new fixture-only credential, never copy the real API credential.
docker run --rm --pull=never --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true --entrypoint python "$image_id" \
  -B -c 'import secrets; print(secrets.token_urlsafe(32))' > "$lab_directory/token"
chmod 600 "$lab_directory/token"
container_id=$(docker run --detach --rm --pull=never --restart=no \
  --name "$lab_name" --label org.nvmagma.auditor.fixture=widget-api \
  --network bridge --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true --memory 128m --pids-limit 64 \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
  --mount "type=bind,source=$repo,target=/checkout,readonly" \
  --mount "type=bind,source=$lab_directory/token,target=/run/secrets/widget-token,readonly" \
  --workdir /checkout --entrypoint python "$image_id" \
  -B /checkout/scripts/integration_widget_fixture.py \
  --token-file /run/secrets/widget-token --scenario "$scenario" --lifetime-seconds 900)
case "$container_id" in ''|*[!0-9a-f]*) exit 2 ;; esac
[ "${#container_id}" -eq 64 ]
ready=false
for attempt in 1 2 3 4 5; do
  if docker exec "$container_id" python -B -c '
import http.client, json, pathlib, sys
connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=2)
try:
    token = pathlib.Path("/run/secrets/widget-token").read_text().strip()
    connection.request("GET", "/api/v1/summary", headers={"Authorization": "Bearer " + token})
    response = connection.getresponse()
    data = json.loads(response.read(4096))
    assert response.status == (503 if sys.argv[1] == "unavailable" else 200)
    assert data["fixture_only"] is True
    assert data["production_authorized"] is False
finally:
    connection.close()
' "$scenario" >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
if [ "$ready" != true ]; then
  printf '%s\n' 'blocked: synthetic API did not become ready; stopping only its new container' >&2
  exit 2
fi
address=$(docker inspect --type container --format '{{with index .NetworkSettings.Networks "bridge"}}{{.IPAddress}}{{end}}' "$container_id")
case "$address" in ''|*[!0-9.]*) exit 2 ;; esac
printf 'widget_fixture_ready=true\nfixture_only=true\nscenario=%s\nfixture_url=http://%s:8080\ncontainer_id=%s\ntoken_file=%s/token\nlifetime_seconds=900\nproduction_authorized=false\n' \
  "$scenario" "$address" "$container_id" "$lab_directory"
# Successful startup leaves only the new fixture running until its hard deadline.
trap - EXIT
