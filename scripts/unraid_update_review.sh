#!/bin/bash
# Read-only host snapshot. Never pull an image, connect a Docker socket inside
# the helper, edit templates, or recreate/start/stop any service.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
templates=${1:-/boot/config/plugins/dockerMan/templates-user}
image=$(docker inspect --format '{{.Image}}' media_collection_auditor)
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo 'status=unverified_local_image' >&2; exit 2; }
docker inspect media_collection_auditor |
  docker run --rm -i --pull=never --network none --read-only --user 0:0 --cap-drop ALL \
    --mount "type=bind,src=$repo,dst=/workspace,readonly" \
    --mount "type=bind,src=$templates,dst=/unraid-templates,readonly" \
    --workdir /workspace --env PYTHONPATH=/workspace --env PYTHONDONTWRITEBYTECODE=1 \
    --entrypoint python "$image" -B -m scripts.unraid_update_review --templates /unraid-templates
