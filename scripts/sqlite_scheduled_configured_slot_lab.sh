#!/usr/bin/env bash
# Existing cached Python image; only a newly created disposable lab is writable.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] || { echo 'Run this acceptance lab on the Linux Docker host.' >&2; exit 2; }
[ "$#" = 1 ] || { echo 'Usage: bash SCRIPT EXISTING_DISPOSABLE_LAB_PARENT' >&2; exit 2; }
base=$1
[[ "$base" = /* && ! "$base" =~ [[:cntrl:],] && -d "$base" ]] || { echo 'Explicit existing lab parent required.' >&2; exit 2; }
[ "$(cd -P -- "$base" && pwd -P)" = "$base" ] || { echo 'Canonical lab parent required.' >&2; exit 2; }
image=${SQLITE_LAB_IMAGE:-python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1}
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ || "$image" =~ ^[a-zA-Z0-9./_:-]+@sha256:[0-9a-f]{64}$ ]] || {
  echo 'Immutable cached image reference required; no pulls/builds.' >&2; exit 2;
}
image_id=$(docker image inspect --format '{{.Id}}' "$image")
[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
volumes=$(docker image inspect --format '{{json .Config.Volumes}}' "$image_id")
[ "$volumes" = null ] || [ "$volumes" = '{}' ] || { echo 'Image-declared volumes refused.' >&2; exit 2; }
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
git diff --quiet HEAD -- app scripts || { echo 'Committed app/scripts sources required for acceptance.' >&2; exit 2; }
source_revision=$(git rev-parse --verify HEAD)
files=()
while IFS= read -r -d '' file; do
  case "$file" in *.py) files+=("$file");; esac
done < <(git ls-files -z -- app scripts)
[ "${#files[@]}" -gt 0 ] || exit 2
for file in "${files[@]}"; do
  [ -f "$file" ] && [ ! -L "$file" ] || { echo 'Regular checkout Python sources required.' >&2; exit 2; }
done
lab=$(mktemp -d "$base/scheduled-configured-slot.XXXXXX")
printf 'SCHEDULED DAILY SLOT DISPOSABLE ONLY\n' > "$lab/.sqlite_scheduled_acceptance_lab"
printf 'Lab directory: %s\n' "$lab"
printf 'source_revision=%s\n' "$source_revision"
printf '%s\n' 'production_activation=disabled' 'production_authorized=false'
container=$(docker create --pull=never --network none --user 0:0 --read-only \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --tmpfs /fixture:rw,noexec,nosuid,nodev,size=64m \
  --mount "type=bind,src=$lab,dst=/lab" --env TMPDIR=/lab \
  --interactive --workdir /fixture --entrypoint /usr/local/bin/python3 "$image_id" \
  -I -S -B -c 'import sys,tarfile,io,os,subprocess; tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode="r:").extractall("/fixture/code",filter="data"); os.chdir("/fixture/code"); subprocess.run([sys.executable,"-S","-B","-m","scripts.sqlite_scheduled_configured_slot_fixture"],check=True,timeout=180); subprocess.run([sys.executable,"-S","-B","-m","scripts.sqlite_scheduled_transport_fixture"],check=True,timeout=30)')
[[ "$container" =~ ^[0-9a-f]{64}$ ]] || { echo 'New fixture container identity unavailable.' >&2; exit 2; }
cleanup() { docker rm --force "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT
COPYFILE_DISABLE=1 tar -cf - -- "${files[@]}" |
  docker start --attach --interactive "$container" | tee "$lab/acceptance.log"
[ "$(docker inspect --format '{{.State.ExitCode}} {{.State.OOMKilled}}' "$container")" = '0 false' ] || exit 1
printf '%s\n' 'status=scheduled_configured_slot_acceptance_complete' \
  'acceptance_scope=configured_disposable_daily_slot' \
  'fixture_only=true' 'production_activation=disabled' 'production_authorized=false' \
  'Only newly created lab files and a new fixture container were used.' \
  'Production media/configuration/services, exports, boot settings and kernel controls were unchanged.'
