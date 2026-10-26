#!/usr/bin/env bash
# New, labeled Jellyfin fixture only; no production mounts, networks or API keys.
set -euo pipefail
umask 077
[ "$#" = 1 ] && [ "$(uname -s)" = Linux ] || exit 2
parent=$1
case "$parent" in /*) :;; *) exit 2;; esac
case "$parent" in *[!a-zA-Z0-9_./-]*) exit 2;; esac
[ -d "$parent" ] && [ "$(readlink -f "$parent")" = "$parent" ]
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
for dependency in docker timeout mktemp readlink; do command -v "$dependency" >/dev/null; done
python_image=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
docker image inspect "$python_image" >/dev/null
# Selected immutable cached image identity only; never inspect environment/config.
jellyfin_image=$(docker inspect --type container --format '{{.Image}}' Jellyfin)
case "$jellyfin_image" in sha256:*) :;; *) exit 2;; esac
[ "${#jellyfin_image}" = 71 ]
reference=$(docker inspect --type container --format '{{.Config.Image}}' Jellyfin)
case "$reference" in jellyfin/jellyfin:*|jellyfin/jellyfin@sha256:*) :;; *)
  printf '%s\n' 'blocked: fixture adapter requires the cached official Jellyfin image' >&2; exit 2;; esac
lab=$(mktemp -d "$parent/jellyfin-ro.XXXXXX")
mkdir "$lab/media" "$lab/config" "$lab/control" "$lab/cache" "$lab/media/Movies"
mkdir "$lab/media/Movies/Fixture Movie (2024)"
printf 'DISPOSABLE JELLYFIN READONLY FIXTURE\n' > "$lab/media/.fixture-only"
cat > "$lab/media/Movies/Fixture Movie (2024)/movie.nfo" <<'XML'
<movie><title>Fixture Movie</title><year>2024</year><lockdata>true</lockdata><tag>keep-forever</tag></movie>
XML
server_id=''
label="jellyfin-ro-${lab##*.}"
ours(){
  case "$server_id" in ''|*[!0-9a-f]*) return 1;; esac
  [ "${#server_id}" = 64 ] && [ "$(docker inspect --type container --format '{{index .Config.Labels "org.nvmagma.auditor.fixture"}}' "$server_id")" = "$label" ]
}
cleanup(){
  if [ -n "$server_id" ]; then
    if ours; then
      if timeout --kill-after=5s 20s docker rm -f "$server_id" >/dev/null; then
        server_id=''
      else
        printf '%s\n' 'fixture_cleanup_failed=true' >&2
        return 1
      fi
    else
      printf '%s\n' 'fixture_identity_lost_no_cleanup_attempted=true' >&2
      return 1
    fi
  fi
}
finish(){
  local outcome=$?
  if [ "$outcome" != 0 ] && ours; then
    docker inspect --format 'fixture_running={{.State.Running}} fixture_exit_code={{.State.ExitCode}} fixture_oom_killed={{.State.OOMKilled}}' "$server_id" || true
    # Retain private logs before removing this new fixture. Never inspect production logs.
    docker logs --tail 100 "$server_id" > "$lab/control/server-startup.log" 2>&1 || true
    printf 'Private fixture diagnostics: %s/control/server-startup.log\n' "$lab"
  fi
  cleanup || return 1
  return "$outcome"
}
trap finish EXIT
printf '%s\n' 'production_activation=disabled' 'writer_exclusion_verified=false'
printf 'Lab directory: %s\n' "$lab"
printf 'cached_jellyfin_image=%s\n' "$jellyfin_image"
# Generate one second of synthetic software-encoded video using the cached image.
timeout --kill-after=5s 30s docker run --rm --pull=never --network none \
  --read-only --cap-drop ALL --security-opt no-new-privileges --memory 256m --pids-limit 64 \
  --label "org.nvmagma.auditor.fixture=$label" \
  --mount "type=bind,src=$lab/media,dst=/out" \
  --entrypoint /usr/bin/timeout "$jellyfin_image" --kill-after=5s 25s /usr/lib/jellyfin-ffmpeg/ffmpeg \
  -hide_banner -loglevel error -nostdin -filter_threads 1 -filter_complex_threads 1 -f lavfi -i color=c=blue:s=32x32:r=1 \
  -t 1 -an -c:v mpeg4 -threads 1 '/out/Movies/Fixture Movie (2024)/Fixture Movie (2024).mkv'
client(){
  local phase=$1 network=none
  if [ "$phase" != prepare ]; then ours; network="container:$server_id"; fi
  timeout --kill-after=5s 180s docker run --rm --pull=never --network "$network" \
    --read-only --cap-drop ALL --security-opt no-new-privileges --memory 128m --pids-limit 64 \
    --label "org.nvmagma.auditor.fixture=$label" -e PYTHONDONTWRITEBYTECODE=1 \
    --mount "type=bind,src=$repo/app,dst=/src/app,readonly" \
    --mount "type=bind,src=$repo/scripts/sqlite_jellyfin_readonly_fixture.py,dst=/src/scripts/sqlite_jellyfin_readonly_fixture.py,readonly" \
    --mount "type=bind,src=$lab/media,dst=/media,readonly" \
    --mount "type=bind,src=$lab/control,dst=/control" \
    "$python_image" python -B /src/scripts/sqlite_jellyfin_readonly_fixture.py --phase "$phase"
}
client prepare
server_id=$(docker create --pull=never --network none --read-only --cap-drop ALL \
  --restart no --security-opt no-new-privileges --memory 768m --cpus 1 --pids-limit 256 \
  --label "org.nvmagma.auditor.fixture=$label" \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m \
  --mount "type=bind,src=$lab/media,dst=/media,readonly" \
  --mount "type=bind,src=$lab/config,dst=/config" \
  --mount "type=bind,src=$lab/cache,dst=/cache" \
  --entrypoint /usr/bin/timeout "$jellyfin_image" --kill-after=5s 300s /jellyfin/jellyfin \
  --datadir /config/data --configdir /config/config --cachedir /cache \
  --logdir /config/log --ffmpeg /usr/lib/jellyfin-ffmpeg/ffmpeg)
case "$server_id" in ''|*[!0-9a-f]*) exit 2;; esac
[ "${#server_id}" = 64 ]
policy(){
  ours
  [ "$(docker inspect --format '{{.HostConfig.NetworkMode}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.Privileged}} {{range .Mounts}}{{if eq .Destination "/media"}}{{.RW}}{{end}}{{end}}' "$server_id")" = 'none true false false' ]
}
policy
docker start "$server_id" >/dev/null
client setup
policy
# Only the newly created, label-verified fixture server is restarted.
timeout --kill-after=5s 30s docker restart --time 5 "$server_id" >/dev/null
policy
client check
trap - EXIT
cleanup
printf '%s\n' 'status=isolated_real_jellyfin_readonly_complete' \
  'Only newly created fixture containers were used; production Jellyfin/NFS/media/configuration unchanged.'
