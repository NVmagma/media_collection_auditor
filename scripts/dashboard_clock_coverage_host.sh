#!/usr/bin/env bash
# Observe the current cached runtime with read-only mounts; no production exec.
set -euo pipefail
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] && [ "$#" = 0 ] || exit 2
[ -z "${DOCKER_HOST:-}" ] && [ -z "${DOCKER_CONTEXT:-}" ] || exit 2
[ "$(docker context inspect --format '{{.Endpoints.docker.Host}}')" = unix:///var/run/docker.sock ] || exit 2
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
image=$(docker inspect --format '{{.Image}}' media_collection_auditor)
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || exit 2
mounts=$(docker inspect --format '{{range .Mounts}}{{printf "%s %s\n" .Type .Destination}}{{end}}' media_collection_auditor | sed '/^$/d' | LC_ALL=C sort)
[ "$mounts" = $'bind /app/logs\nbind /media\nbind /sqlite-control' ] || exit 2
volumes=$(docker image inspect --format '{{json .Config.Volumes}}' "$image")
[ "$volumes" = null ] || [ "$volumes" = '{}' ] || exit 2
docker inspect media_collection_auditor | docker run --rm -i --pull=never --network none --read-only \
  --user 0:0 --cap-drop ALL --security-opt no-new-privileges --memory 256m --pids-limit 64 \
  --volumes-from media_collection_auditor:ro \
  --mount "type=bind,src=$checkout,dst=/review-source,readonly" --workdir /app \
  --env PYTHONPATH=/app:/app/app:/review-source --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python "$image" -B -m scripts.dashboard_clock_coverage
