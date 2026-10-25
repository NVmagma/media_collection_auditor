#!/usr/bin/env bash
# New candidate container + new lab directory only. Host Python is not required.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] || { echo 'Run on the Linux Docker host.' >&2; exit 2; }
[ "$#" = 2 ] || { echo 'Usage: bash SCRIPT FULL_CANDIDATE_IMAGE_ID EXISTING_LAB_PARENT' >&2; exit 2; }
image=$1
base=$2
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
[[ "$base" = /* && ! "$base" =~ [[:cntrl:],] && -d "$base" ]] || exit 2
[ "$(cd -P -- "$base" && pwd -P)" = "$base" ] || exit 2
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 2
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || exit 2
[ "$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.sqlite-activation"}}' "$image")" = disabled ] || exit 2
volumes=$(docker image inspect --format '{{json .Config.Volumes}}' "$image")
[ "$volumes" = null ] || [ "$volumes" = '{}' ] || exit 2
git cat-file -e "$revision:app/sqlite_disposable_restore.py"
git cat-file -e "$revision:scripts/sqlite_restore_fixture.py"
lab=$(mktemp -d "$base/restore.XXXXXX")
printf 'Lab directory: %s\nsource_revision=%s\nimage_id=%s\n' "$lab" "$revision" "$image"
printf '%s\n' 'production_activation=disabled' 'production_authorized=false'
container=$(docker create --pull=never --network none --user "$(id -u):$(id -g)" --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --tmpfs "/tools:rw,noexec,nosuid,nodev,size=32m,mode=0700,uid=$(id -u),gid=$(id -g)" --tmpfs /tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777 \
  --mount "type=bind,src=$lab,dst=/lab" --env TMPDIR=/lab --env PYTHONPATH=/tools:/app:/app/app \
  --interactive --workdir /tools --entrypoint python "$image" -B -c \
  'import io,os,sys,tarfile,subprocess,tempfile; from pathlib import Path; from pathlib import Path; assert os.stat("/lab").st_uid==os.geteuid() and tempfile.gettempdir()=="/lab", "Actual host-backed temp directory required"; import app.sqlite_disposable_restore as m; assert Path(m.__file__).is_relative_to("/app/app"); tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode="r:").extractall("/tools",filter="data"); subprocess.run([sys.executable,"-B","-m","scripts.sqlite_restore_fixture"],check=True,timeout=180)')
[[ "$container" =~ ^[0-9a-f]{64}$ ]] || exit 2
cleanup() { docker rm --force "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT
git archive --format=tar "$revision" scripts |
  docker start --attach --interactive "$container" | tee "$lab/acceptance.log"
[ "$(docker inspect --format '{{.State.ExitCode}} {{.State.OOMKilled}}' "$container")" = '0 false' ] || exit 1
printf '%s\n' 'status=restore_acceptance_complete' 'acceptance_scope=disposable_advanced_state_restore' \
  'fixture_only=true' 'production_restore_performed=false' 'production_activation=disabled' \
  'production_authorized=false' 'Only new fixture files and a new candidate container were used.'
