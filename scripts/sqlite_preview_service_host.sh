#!/usr/bin/env bash
# Production entrypoint. review is read-only; deploy/rollback require explicit
# human approval of the exact image, private selection fingerprint and revision.
# Never source private env/JSON, use eval, pull an image, remove the old auditor,
# change daemon settings, or automatically resume a failed transaction.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] && [ "$(id -u)" = 0 ] || { echo 'Run on Tower as root.' >&2; exit 2; }
[ "$#" = 5 ] || [ "$#" = 6 ] || { echo 'Usage: bash SCRIPT review|deploy|deploy-published|rollback IMAGE_ID PRIVATE_PACKET SELECTION_FINGERPRINT CONTROLLER_REVISION [PUBLISHED_REFERENCE|REVIEWED_PREVIEW_ID]' >&2; exit 2; }
action=$1 image=$2 packet=$3 selection=$4 controller_revision=$5
reviewed_preview=''
published_reference=''
if [ "$action" = deploy-published ]; then published_reference=${6:-}; else reviewed_preview=${6:-}; fi
[[ "$action" = review || "$action" = deploy || "$action" = deploy-published || "$action" = rollback ]] || exit 2
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ && "$selection" =~ ^[0-9a-f]{64}$ && "$controller_revision" =~ ^[0-9a-f]{40}$ ]] || exit 2
if [ "$action" = deploy-published ]; then
  [[ "$published_reference" =~ ^ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}$ ]] || exit 2
fi
if [ -n "$reviewed_preview" ]; then
  [ "$action" = rollback ] && [[ "$reviewed_preview" =~ ^[0-9a-f]{64}$ ]] || exit 2
fi
[[ "$packet" = /* && ! "$packet" =~ [[:cntrl:],] && -d "$packet" && ! -L "$packet" ]] || exit 2
[ "$(cd -P -- "$packet" && pwd -P)" = "$packet" ] || exit 2
exec {packet_fd}<"$packet"
anchor="/proc/$$/fd/$packet_fd"
[ "$(stat -Lc '%u:%a' -- "$anchor")" = 0:700 ] || exit 2
packet_identity=$(stat -Lc '%d:%i' -- "$anchor")
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
git_cmd=(git -c "safe.directory=$checkout")
[ "$("${git_cmd[@]}" branch --show-current)" = feature/sqlite ] || exit 2
[ "$("${git_cmd[@]}" rev-parse --verify HEAD)" = "$controller_revision" ] || exit 2
"${git_cmd[@]}" diff --quiet HEAD -- app scripts || { echo 'Committed controller/runtime files required.' >&2; exit 2; }
"${git_cmd[@]}" cat-file -e "$controller_revision:scripts/sqlite_preview_release_request.py"
# Do not accidentally publish/control a remote Docker context using local binds.
if [ -n "${DOCKER_CONTEXT:-}" ]; then
  endpoint=$(docker context inspect --format '{{(index .Endpoints "docker").Host}}' "$DOCKER_CONTEXT")
elif [ -n "${DOCKER_HOST:-}" ]; then
  endpoint=$DOCKER_HOST
else
  context=$(docker context show)
  endpoint=$(docker context inspect --format '{{(index .Endpoints "docker").Host}}' "$context")
fi
[[ "$endpoint" = unix:///var/run/docker.sock || "$endpoint" = unix:///run/docker.sock ]] || {
  echo 'Local Tower Docker socket context required.' >&2; exit 2;
}
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || exit 2
[ "$(docker image inspect --format '{{index .Config.Labels "io.media-collection-auditor.sqlite-activation"}}' "$image")" = preview-only ] || exit 2
worker_revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")
[[ "$worker_revision" =~ ^[0-9a-f]{40}$ ]] || exit 2
"${git_cmd[@]}" diff --quiet "$worker_revision" "$controller_revision" -- app || {
  echo 'Accepted worker app code differs from controller expectations.' >&2; exit 2;
}
volumes=$(docker image inspect --format '{{json (index .Config "Volumes")}}' "$image")
[ "$volumes" = null ] || [ "$volumes" = '{}' ] || exit 2
helper=''
cleanup() { [ -z "$helper" ] || docker rm --force "$helper" >/dev/null 2>&1 || true; }
trap cleanup EXIT
trap 'echo "status=deployment_stopped_for_review automatic_restoration=false" >&2' ERR

request() {
  local operation=$1
  # Ordinary bind path for runc; request verifier compares the mounted identity
  # against our held descriptor before reading any private contents.
  "${git_cmd[@]}" archive --format=tar "$controller_revision" scripts |
    docker run --rm --pull=never --network none --read-only --user 0:0 --cap-drop ALL \
      --security-opt no-new-privileges --pids-limit 64 --memory 256m \
      --tmpfs /tools:rw,noexec,nosuid,nodev,size=32m,mode=0700 \
      --mount "type=bind,src=$packet,dst=/packet,readonly" \
      --env PYTHONPATH=/tools:/app:/app/app --interactive --workdir /tools --entrypoint python "$image" -B -c \
      'import io,sys,tarfile,subprocess; tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode="r:").extractall("/tools",filter="data"); subprocess.run([sys.executable,"-B","-m","scripts.sqlite_preview_release_request",*sys.argv[1:]],check=True)' \
      "$operation" --packet-directory /packet --packet-identity "$packet_identity" --image-id "$image" --selection-fingerprint "$selection" || return 1
  [ ! -L "$packet" ] && [ "$(stat -Lc '%d:%i' -- "$packet")" = "$packet_identity" ] || return 1
}

if [ "$action" = review ]; then
  request review
  exit 0
fi

# Fully verify private inputs and the exact approved selection before any tag,
# publication, host directory creation or production service action.
review_sha=$(request review-sha)
[[ "$review_sha" =~ ^[0-9a-f]{64}$ ]] || exit 1
repository=ghcr.io/nvmagma/media_collection_auditor
control=$(request control-path)
[[ "$control" = /* && ! "$control" =~ [[:cntrl:],] ]] || exit 1
if [[ "$action" = deploy || "$action" = deploy-published ]]; then
  [ ! -e "$control" ] && [ ! -L "$control" ] || { echo 'Control destination occupied; no deployment attempted.' >&2; exit 1; }
  if [ "$action" = deploy-published ]; then
    reference=$published_reference
    [ "$(docker image inspect --format '{{.Id}}' "$reference")" = "$image" ] || exit 1
  else
    release_tag="$repository:sqlite-preview-${worker_revision:0:12}-${image#sha256:}"
    docker tag "$image" "$release_tag"
    docker push "$release_tag"
    digests=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$image")
    reference=''
    while IFS= read -r candidate; do
      if [[ "$candidate" =~ ^ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}$ ]]; then
        reference=$candidate
        break
      fi
    done <<< "$digests"
    [[ "$reference" =~ ^ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}$ ]] || exit 1
    [ "$(docker image inspect --format '{{.Id}}' "$reference")" = "$image" ] || exit 1
  fi
  # Exclusive root creation. Existing appdata, media, templates and permissions
  # are not changed here. The offline controller backs up settings before writes.
  mkdir -m 700 -- "$control"
else
  reference=$(request reference)
  [[ "$reference" =~ ^ghcr\.io/nvmagma/media_collection_auditor@sha256:[0-9a-f]{64}$ ]] || exit 1
  [ "$(docker image inspect --format '{{.Id}}' "$reference")" = "$image" ] || exit 1
fi
[ ! -L "$control" ] && [ "$(stat -Lc '%u:%a' -- "$control")" = 0:700 ] || exit 1
exec {control_fd}<"$control"
control_identity=$(stat -Lc '%d:%i' -- "/proc/$$/fd/$control_fd")
daemon=$(docker info --format '{{.ID}}')
[[ "$daemon" =~ ^[A-Za-z0-9:_.-]+$ ]] || exit 1
mode=apply
[ "$action" != rollback ] || mode=rollback
extra=()
[ -z "$reviewed_preview" ] || extra=(--reviewed-preview-container-id "$reviewed_preview")
helper=$(docker create --pull=never --network bridge --read-only --user 0:0 --cap-drop ALL \
  --cap-add DAC_OVERRIDE --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --tmpfs /tools:rw,noexec,nosuid,nodev,size=32m,mode=0700 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777 \
  --mount type=bind,src=/var/run/docker.sock,dst=/docker-engine.sock \
  --mount "type=bind,src=$packet,dst=/packet" \
  --mount "type=bind,src=$control,dst=/sqlite-control" \
  --mount type=bind,src=/mnt/user/appdata/media_collection_auditor,dst=/app/logs \
  --mount type=bind,src=/mnt/user/media_storage,dst=/media,readonly \
  --mount type=bind,src=/boot/config/plugins/dockerMan/templates-user,dst=/unraid-templates \
  --env PYTHONPATH=/tools:/app:/app/app --interactive --workdir /tools --entrypoint python "$image" -B -c \
  'import io,sys,tarfile,subprocess; tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode="r:").extractall("/tools",filter="data"); subprocess.run([sys.executable,"-B","-m","scripts.sqlite_preview_service",*sys.argv[1:]],check=True)' \
  "$mode" --packet-directory /packet --packet-identity "$packet_identity" --control-identity "$control_identity" \
  --image-id "$image" --published-reference "$reference" --approved-review-sha256 "$review_sha" \
  --daemon-id "$daemon" --controller-revision "$controller_revision" "${extra[@]}")
[[ "$helper" =~ ^[0-9a-f]{64}$ ]] || exit 1
"${git_cmd[@]}" archive --format=tar "$controller_revision" scripts | docker start --attach --interactive "$helper"
[ "$(docker inspect --format '{{.State.ExitCode}} {{.State.OOMKilled}}' "$helper")" = '0 false' ] || exit 1
printf '%s\n' 'status=explicit_service_transaction_finished' 'automatic_restoration=false'
