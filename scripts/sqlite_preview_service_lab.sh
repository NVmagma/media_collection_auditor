#!/usr/bin/env bash
# Only new randomly named fixture containers and files. The adapter admits only
# its recorded IDs/new lab mounts; no production service name is used by Docker.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] && { [ "$#" = 1 ] || [ "$#" = 2 ]; } || {
  echo 'Run on the Linux Docker host as root: bash SCRIPT ACCEPTED_PREVIEW_IMAGE_ID [service|fresh]' >&2; exit 2;
}
image=$1
fixture_mode=${2:-service}
[[ "$fixture_mode" = service || "$fixture_mode" = fresh ]] || exit 2
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
git_cmd=(git -c "safe.directory=$checkout")
controller_revision=$("${git_cmd[@]}" rev-parse --verify HEAD)
revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")
[[ "$controller_revision" =~ ^[0-9a-f]{40}$ && "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 2
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || exit 2
[ "$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.sqlite-activation"}}' "$image")" = preview-only ] || exit 2
volumes=$(docker image inspect --format '{{json (index .Config "Volumes")}}' "$image")
[ "$volumes" = null ] || [ "$volumes" = '{}' ] || exit 2
"${git_cmd[@]}" diff --quiet "$revision" "$controller_revision" -- app || {
  echo 'Accepted worker image must contain the same app code as the controller expects.' >&2; exit 2;
}
"${git_cmd[@]}" cat-file -e "$controller_revision:scripts/sqlite_preview_service_docker_fixture.py"
daemon=$(docker info --format '{{.ID}}')
[[ "$daemon" =~ ^[A-Za-z0-9:_.-]+$ ]] || exit 2
# A fresh local Docker volume provides protected host ancestors for daemon bind
# sources. Shared /mnt lab parents can be renamed by other users and are not used
# as a source for newly created workers in this service-level fixture.
nonce=$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')
[[ "$nonce" =~ ^[0-9a-f]{16}$ ]] || exit 2
volume="auditor-service-fixture-$nonce"
if docker volume inspect "$volume" >/dev/null 2>&1; then exit 2; fi
[ "$(docker volume create --driver local --label "io.media-collection-auditor.service-fixture=$nonce" "$volume")" = "$volume" ] || exit 1
lab=$(docker volume inspect --format '{{.Mountpoint}}' "$volume")
[ "$(docker volume inspect --format '{{.Driver}}' "$volume")" = local ] || exit 1
options=$(docker volume inspect --format '{{json .Options}}' "$volume")
[ "$options" = null ] || [ "$options" = '{}' ] || exit 1
[ "$(docker volume inspect --format '{{index .Labels "io.media-collection-auditor.service-fixture"}}' "$volume")" = "$nonce" ] || exit 1
[[ "$lab" = /* && ! "$lab" =~ [[:cntrl:],] ]] || exit 1
directory=$lab
while :; do
  [ ! -L "$directory" ] || exit 1
  read -r owner mode <<< "$(stat -Lc '%u %a' -- "$directory")"
  [ "$owner" = 0 ] || exit 1
  (( (8#$mode & 8#22) == 0 || (8#$mode & 8#1000) != 0 )) || exit 1
  [ "$directory" != / ] || break
  directory=$(dirname -- "$directory")
done
printf 'Fixture volume: %s\nworker_revision=%s\ncontroller_revision=%s\nimage_id=%s\n' "$volume" "$revision" "$controller_revision" "$image"
printf '%s\n' 'production_authorized=false' 'registry_publication_performed=false' 'host_ports_published=false'
docker run --rm --pull=never --network none --read-only --user 0:0 --cap-drop ALL \
  --mount "type=volume,src=$volume,dst=/lab" --entrypoint python "$image" -B -c \
  'import os; from pathlib import Path; root=Path("/lab"); assert not list(root.iterdir()); os.chmod(root,0o700); [root.joinpath(p).mkdir(mode=0o700) for p in ("packet","logs","control","media","templates")]; [root.joinpath("media",p).mkdir(mode=0o700) for p in ("Movies","Movies_hold","Movies_keep","Movies_removal")]'
container=$(docker create --pull=never --network bridge --read-only --user 0:0 --cap-drop ALL \
  --cap-add DAC_OVERRIDE --cap-add CHOWN --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --tmpfs /tools:rw,noexec,nosuid,nodev,size=32m,mode=0700 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777 \
  --mount type=bind,src=/var/run/docker.sock,dst=/docker-engine.sock \
  --mount "type=volume,src=$volume,dst=/lab" --mount "type=bind,src=$lab/packet,dst=/packet" \
  --mount "type=bind,src=$lab/logs,dst=/app/logs" --mount "type=bind,src=$lab/control,dst=/sqlite-control" \
  --mount "type=bind,src=$lab/media,dst=/media,readonly" --mount "type=bind,src=$lab/templates,dst=/unraid-templates" \
  --env "FIXTURE_MODE=$fixture_mode" --env TMPDIR=/lab --env "EXPECTED_RELEASE_REVISION=$revision" --env "EXPECTED_CONTROLLER_REVISION=$controller_revision" \
  --env "EXPECTED_PREVIEW_IMAGE=$image" --env "EXPECTED_DAEMON_ID=$daemon" --env "HOST_FIXTURE_ROOT=$lab" \
  --env PYTHONPATH=/tools:/app:/app/app --interactive --workdir /tools --entrypoint python "$image" -B -c \
  'import io,os,sys,tarfile,subprocess,tempfile; assert os.stat("/lab").st_uid==0 and tempfile.gettempdir()=="/lab"; tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode="r:").extractall("/tools",filter="data"); modules=("scripts.sqlite_preview_fresh_fixture",) if os.environ["FIXTURE_MODE"]=="fresh" else ("scripts.sqlite_preview_service_fixture","scripts.sqlite_preview_service_docker_fixture"); [subprocess.run([sys.executable,"-B","-m",module],check=True,timeout=180) for module in modules]')
[[ "$container" =~ ^[0-9a-f]{64}$ ]] || exit 2
cleanup() { [ -z "$container" ] || docker rm --force "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT
"${git_cmd[@]}" archive --format=tar "$controller_revision" scripts | docker start --attach --interactive "$container"
[ "$(docker inspect --format '{{.State.ExitCode}} {{.State.OOMKilled}}' "$container")" = '0 false' ] || exit 1
cleanup
container=''
[ "$(docker volume inspect --format '{{index .Labels "io.media-collection-auditor.service-fixture"}}' "$volume")" = "$nonce" ] || exit 1
docker volume rm "$volume" >/dev/null
printf 'fixture_mode=%s\n' "$fixture_mode"
printf '%s\n' 'status=scoped_preview_service_acceptance_complete' 'fixture_only=true' \
  'production_authorized=false' 'registry_publication_performed=false' 'host_ports_published=false' \
  'Only new fixture containers/files were used; existing auditor and Unraid templates unchanged.'
