#!/usr/bin/env bash
# Actual default entrypoint, private API and image-app fixtures; no host Python.
set -euo pipefail
umask 077
[ "$#" = 1 ] || { echo 'Usage: bash SCRIPT FULL_CACHED_CANDIDATE_IMAGE_ID' >&2; exit 2; }
image=$1
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo 'Immutable cached image ID required.' >&2; exit 2; }
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 2
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || exit 2
[ "$(docker image inspect --format '{{json .Config.Entrypoint}}' "$image")" = '["python","-m","app.main"]' ] || exit 2
[ "$(docker image inspect --format '{{.Config.StopSignal}}' "$image")" = SIGINT ] || exit 2
[ "$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.sqlite-activation"}}' "$image")" = disabled ] || exit 2
volumes=$(docker image inspect --format '{{json .Config.Volumes}}' "$image")
[ "$volumes" = null ] || [ "$volumes" = '{}' ] || exit 2
git cat-file -e "$revision:scripts/sqlite_candidate_image_lab.py"
printf 'source_revision=%s\nimage_id=%s\n' "$revision" "$image"
container=$(docker create --pull=never --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=128m \
  --env READ_ONLY_API_SERVICE=true --env STATE_FILE=/tmp/state.json --env WEB_PORT=8080 \
  --env WEB_SESSION_SECRET=disposable-image-fixture-secret \
  --env INTEGRATION_API_TOKEN=disposable_candidate_image_token_0123456789 "$image")
[[ "$container" =~ ^[0-9a-f]{64}$ ]] || exit 2
cleanup() { docker rm --force "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker start "$container" >/dev/null
git show "$revision:scripts/sqlite_candidate_image_lab.py" |
  docker exec --interactive "$container" python -B -c 'import sys,runpy; from pathlib import Path; p=Path("/tmp/candidate-image-helper.py"); p.write_bytes(sys.stdin.buffer.read()); m=runpy.run_path(str(p),run_name="candidate_helpers"); exec(m["PROBE"])'
git archive --format=tar "$revision" scripts |
  docker exec --interactive "$container" python -B -c 'import runpy; m=runpy.run_path("/tmp/candidate-image-helper.py",run_name="candidate_helpers"); exec(m["FIXTURES"])'
docker stop --time 5 "$container" >/dev/null
status=$(docker inspect --format '{{.State.Running}} {{.State.OOMKilled}} {{.State.ExitCode}}' "$container")
[ "$status" = 'false false 0' ] || [ "$status" = 'false false 143' ] || { echo 'Candidate did not stop cleanly.' >&2; exit 1; }
printf '%s\n' 'status=candidate_image_acceptance_complete' 'fixture_only=true' \
  'host_mounts=false' 'published_ports=false' 'registry_push_performed=false' \
  'production_activation=disabled' 'production_authorized=false'
