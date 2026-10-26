#!/usr/bin/env bash
# Observe only: no pulls, production exec, service/template changes or rebinding.
set -euo pipefail
[ "$#" = 1 ] || { echo 'Usage: bash SCRIPT FULL_CACHED_CANDIDATE_IMAGE_ID' >&2; exit 2; }
image=$1
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo 'Exact cached image ID required.' >&2; exit 2; }
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || exit 2
volumes=$(docker image inspect --format '{{json .Config.Volumes}}' "$image")
[ "$volumes" = null ] || [ "$volumes" = '{}' ] || { echo 'Image-declared volumes refused.' >&2; exit 2; }
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
# Inherit only the known directory layout; never inherit an unexpected socket
# or unrelated mount, even when Docker marks that bind read-only.
mounts=$(docker inspect --format '{{range .Mounts}}{{printf "%s %s\n" .Type .Destination}}{{end}}' media_collection_auditor | sort)
[ "$mounts" = $'bind /app/logs\nbind /media\nbind /sqlite-control' ] || {
  echo 'Exactly the reviewed three bind mounts are required.' >&2; exit 2;
}
{
  printf '{"containers":'
  docker inspect media_collection_auditor
  printf ',"images":'
  docker image inspect "$image"
  printf '}\n'
} | docker run --rm -i --pull=never --network none --read-only --user 0:0 \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --volumes-from media_collection_auditor:ro \
  --mount "type=bind,src=$checkout,dst=/review-source,readonly" \
  --workdir /app --env PYTHONPATH=/app:/app/app:/review-source --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python "$image" -B -m scripts.unraid_proposed_update_review
