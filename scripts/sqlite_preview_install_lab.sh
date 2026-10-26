#!/usr/bin/env bash
# Only NEW lab files/containers; no existing auditor or host services controlled.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] && [ "$#" = 2 ] || exit 2
image=$1 base=$2
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
[[ "$base" = /* && ! "$base" =~ [[:cntrl:],] && -d "$base" ]] || exit 2
[ "$(cd -P -- "$base" && pwd -P)" = "$base" ] || exit 2
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 2
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || exit 2
[ "$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.sqlite-activation"}}' "$image")" = preview-only ] || exit 2
volumes=$(docker image inspect --format '{{json (index .Config "Volumes")}}' "$image")
[ "$volumes" = null ] || [ "$volumes" = '{}' ] || exit 2
git cat-file -e "$revision:app/sqlite_preview_install.py"
lab=$(mktemp -d "$base/preview-install.XXXXXX")
mkdir -- "$lab/packet" "$lab/logs" "$lab/control" "$lab/media"
mkdir -- "$lab/media/Movies" "$lab/media/Movies_hold" "$lab/media/Movies_keep" "$lab/media/Movies_removal"
printf 'Lab directory: %s\nsource_revision=%s\nimage_id=%s\n' "$lab" "$revision" "$image"
printf '%s\n' 'production_authorized=false' 'media_actions_authorized=false'
container=$(docker create --pull=never --network none --read-only --user "$(id -u):$(id -g)" --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --tmpfs "/tools:rw,noexec,nosuid,nodev,size=32m,mode=0700,uid=$(id -u),gid=$(id -g)" \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777 \
  --mount "type=bind,src=$lab,dst=/lab" --mount "type=bind,src=$lab/packet,dst=/packet" \
  --mount "type=bind,src=$lab/logs,dst=/app/logs" --mount "type=bind,src=$lab/control,dst=/sqlite-control" \
  --mount "type=bind,src=$lab/media,dst=/media,readonly" --env TMPDIR=/lab \
  --env "EXPECTED_RELEASE_REVISION=$revision" --env "EXPECTED_PREVIEW_IMAGE=$image" --env PYTHONPATH=/tools:/app:/app/app \
  --interactive --workdir /tools --entrypoint python "$image" -B -c \
  'import io,os,sys,tarfile,subprocess,tempfile; assert os.stat("/lab").st_uid==os.geteuid() and tempfile.gettempdir()=="/lab"; tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode="r:").extractall("/tools",filter="data"); subprocess.run([sys.executable,"-B","-m","scripts.sqlite_preview_install_fixture","--actual-image"],check=True,timeout=180)')
[[ "$container" =~ ^[0-9a-f]{64}$ ]] || exit 2
cleanup() { docker rm --force "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT
git archive --format=tar "$revision" scripts | docker start --attach --interactive "$container" | tee "$lab/acceptance.log"
[ "$(docker inspect --format '{{.State.ExitCode}} {{.State.OOMKilled}}' "$container")" = '0 false' ] || exit 1
printf '%s\n' 'status=offline_preview_install_acceptance_complete' 'fixture_only=true' \
  'production_authorized=false' 'service_actions_performed=false' 'media_actions_authorized=false' \
  'Only new fixture files and one new container were used; production remains unchanged.'
