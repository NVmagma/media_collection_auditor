#!/usr/bin/env bash
# Host Python is not required. Build only committed bytes; never tag or publish.
set -euo pipefail
umask 077
[ "$#" -le 1 ] || { echo 'Usage: bash SCRIPT [PINNED_PYTHON_BASE]' >&2; exit 2; }
base=${1:-python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704}
[[ "$base" =~ ^python@sha256:[0-9a-f]{64}$ ]] || { echo 'Pinned official Python digest required.' >&2; exit 2; }
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
[ "$(git branch --show-current)" = feature/sqlite ] || { echo 'Build requires feature/sqlite.' >&2; exit 2; }
git diff --quiet HEAD -- app scripts docker requirements.txt unraid/assets/Media_Collection_Auditor_Badge.png || {
  echo 'Committed candidate build/runtime inputs required.' >&2; exit 2;
}
revision=$(git rev-parse --verify HEAD)
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 2
iid=$(mktemp)
trap 'rm -f -- "$iid"' EXIT
printf 'source_revision=%s\nproduction_activation=preview-capable\nregistry_push_performed=false\n' "$revision" >&2
git archive --format=tar "$revision" |
  docker build --pull=false --file docker/sqlite-preview-release.Dockerfile \
    --build-arg "BASE_IMAGE=$base" --build-arg "SOURCE_REVISION=$revision" --iidfile "$iid" - >&2
raw=$(cat -- "$iid")
[[ "$raw" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
image=$(docker image inspect --format '{{.Id}}' "$raw")
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
printf '%s\n' "$image"
