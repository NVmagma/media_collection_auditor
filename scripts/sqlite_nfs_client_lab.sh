#!/usr/bin/env bash
# Real NFSv3 RPC fixture; private net/PID/mount namespaces and private RPC state.
# No host service scripts, production exports, client kernel mounts or builds.
set -euo pipefail
printf '%s\n' 'production_activation=disabled' 'writer_exclusion_verified=false'
if [ "$#" -ne 1 ] || [ "$(uname -s)" != Linux ] || [ "$EUID" -ne 0 ]; then
  printf '%s\n' 'Usage: bash scripts/sqlite_nfs_client_lab.sh EXISTING_ABSOLUTE_LAB_PARENT' >&2
  exit 2
fi
parent=$1
case "$parent" in /*) :;; *) exit 2;; esac
# Restriction belongs to this shell lab's generated export syntax, not the app.
case "$parent" in *[!a-zA-Z0-9_./-]*) printf '%s\n' 'blocked=unsupported_lab_path_characters' >&2; exit 2;; esac
for dependency in docker nsenter unshare timeout mount umount readlink mktemp cat awk stat ip rpcbind rpc.mountd rpcinfo exportfs sha256sum cp mkdir sleep seq touch dirname tail; do
  command -v "$dependency" >/dev/null 2>&1 || { printf 'blocked=missing:%s\n' "$dependency" >&2; exit 2; }
done
[ -d "$parent" ] && [ "$(readlink -f "$parent")" = "$parent" ]
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
image=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
docker image inspect "$image" >/dev/null
host_net=$(readlink /proc/self/ns/net)
host_mnt=$(readlink /proc/self/ns/mnt)
host_control=$(stat -Lc '%d:%i' /proc/fs/nfsd/threads)
host_threads=$(cat /proc/fs/nfsd/threads)
case "$host_threads" in ''|*[!0-9]*) exit 2;; esac
host_exports=$(sha256sum /etc/exports | awk '{print $1}')
host_etab=$(sha256sum /var/lib/nfs/etab | awk '{print $1}')
lab=$(mktemp -d "$parent/nfs-client.XXXXXX")
mkdir "$lab/control" "$lab/data" "$lab/etc"
printf 'DISPOSABLE NFS RPC LAB\n' > "$lab/control/.disposable_nfs_rpc"
printf 'INITIAL\n' > "$lab/data/payload.bin"
# Only these non-secret name/service maps are copied, never arbitrary host config.
for item in netconfig services passwd group nsswitch.conf hosts; do
  [ ! -r "/etc/$item" ] || cp -- "/etc/$item" "$lab/etc/$item"
done
printf '%s 127.0.0.1(rw,sync,no_subtree_check,no_root_squash,insecure,fsid=28173)\n' "$lab/data" > "$lab/etc/exports"
printf '[general]\nstate-directory-path=/var/lib/nfs\n' > "$lab/etc/nfs.conf"
container_id=
client_net_fd=
cleanup(){
  if [ -n "$container_id" ]; then docker rm -f "$container_id" >/dev/null 2>&1 || true; fi
  if [ -n "$client_net_fd" ]; then exec {client_net_fd}<&-; fi
}
trap cleanup EXIT
printf 'Lab directory: %s\nhost_threads_before=%s\n' "$lab" "$host_threads"
container_id=$(docker run -d --pull=never --network none --read-only --cap-drop ALL \
  --label media-auditor.disposable-nfs-client=true \
  --security-opt no-new-privileges --tmpfs /tmp:rw \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$repo:/src:ro" -v "$lab/control:/control:rw" \
  "$image" python -B /src/scripts/sqlite_nfs_rpc_client_lab.py \
  --control /control --export "$lab/data" --host-netns "$host_net")
client_pid=$(docker inspect --format '{{.State.Pid}}' "$container_id")
case "$client_pid" in ''|*[!0-9]*|0) printf '%s\n' 'blocked=client_not_running' >&2; exit 2;; esac
# Pin the namespace itself so later PID reuse cannot retarget nsenter.
exec {client_net_fd}<"/proc/$client_pid/ns/net"
client_net=$(readlink "/proc/self/fd/$client_net_fd")
[ "$(docker inspect --format '{{.State.Pid}}' "$container_id")" = "$client_pid" ]
[ "$(readlink "/proc/$client_pid/ns/net")" = "$client_net" ]
[ "$client_net" != "$host_net" ]
printf 'Disposable client container: %s\n' "$container_id"
server_status=0
timeout --kill-after=5s 100s \
  nsenter --net="/proc/self/fd/$client_net_fd" \
  unshare --mount --pid --fork --kill-child --mount-proc --propagation private \
  bash -euo pipefail -s -- "$lab" "$host_net" "$host_mnt" "$host_control" "$client_net" <<'SERVER' || server_status=$?
lab=$1; host_net=$2; host_mnt=$3; host_control=$4; client_net=$5
control=/proc/fs/nfsd
namespaces(){
  [ "$(readlink /proc/self/ns/net)" = "$client_net" ] &&
    [ "$client_net" != "$host_net" ] &&
    [ "$(readlink /proc/self/ns/mnt)" != "$host_mnt" ]
}
namespaces
# Utilities cannot reach production exports, RPC UNIX sockets or state paths.
mount -n --bind "$lab/etc" /etc
mount -n -t tmpfs -o size=16m,nosuid,nodev tmpfs /var/lib
mount -n -t tmpfs -o size=8m,nosuid,nodev tmpfs /run
# /var/run is not assumed to be a symlink to /run on every deployment.
if [ "$(readlink -f /var/run)" != /run ]; then
  mount -n -t tmpfs -o size=8m,nosuid,nodev tmpfs /var/run
fi
mkdir -p /var/lib/nfs /var/lib/rpcbind /run/rpcbind /var/run/rpcbind
unset LISTEN_PID LISTEN_FDS LISTEN_FDNAMES
mount -n -t nfsd -o nosuid,nodev,noexec nfsd "$control"
thread_id=$(stat -Lc '%d:%i' "$control/threads")
version_id=$(stat -Lc '%d:%i' "$control/versions")
[ "$thread_id" != "$host_control" ] && [ "$(cat "$control/threads")" = 0 ]
verify(){
  namespaces && [ "$(stat -f -c %t "$control")" = 6e667364 ] &&
    [ "$(stat -Lc '%d:%i' "$control/threads")" = "$thread_id" ] &&
    [ "$(stat -Lc '%d:%i' "$control/versions")" = "$version_id" ]
}
started=0
cleanup_server(){
  result=$?
  trap - EXIT
  # Only bound private control; PID namespace teardown also ends lab daemons.
  if [ "$started" = 1 ]; then
    if verify && printf '0\n' > "$control/threads" && [ "$(cat "$control/threads")" = 0 ]; then :;
    else result=2; fi
  fi
  exit "$result"
}
trap cleanup_server EXIT
trap 'exit 2' INT TERM
wait_file(){
  for attempt in $(seq 1 300); do
    [ ! -f "$lab/control/$1" ] || return 0
    sleep 0.05
  done
  printf 'blocked=phase_timeout:%s\n' "$1" >&2
  return 2
}
payload_matches(){
  expected=$(printf '%s\n' "$1" | sha256sum | awk '{print $1}')
  [ "$(sha256sum "$lab/data/payload.bin" | awk '{print $1}')" = "$expected" ]
}
verify
printf '%s\n' '-4' > "$control/versions"
versions=$(cat "$control/versions")
case " $versions " in *' +4'*|*' +2'*) exit 2;; esac
case " $versions " in *' +3 '*) :;; *) exit 2;; esac
ip link set lo up
rpcbind -f > "$lab/rpcbind.log" 2>&1 &
for attempt in $(seq 1 50); do
  if rpcinfo -p 127.0.0.1 >/dev/null 2>&1; then break; fi
  sleep 0.1
done
rpcinfo -p 127.0.0.1 >/dev/null
verify
exportfs -ra > "$lab/exportfs.log" 2>&1
rpc.mountd -F -N 4 -p 20048 -s /var/lib/nfs > "$lab/mountd.log" 2>&1 &
for attempt in $(seq 1 50); do
  if rpcinfo -n 20048 -t 127.0.0.1 100005 3 >/dev/null 2>&1; then break; fi
  sleep 0.1
done
rpcinfo -n 20048 -t 127.0.0.1 100005 3 >/dev/null
verify
started=1
printf '1\n' > "$control/threads"
verify
[ "$(cat "$control/threads")" = 1 ]
touch "$lab/control/server.ready"
wait_file client.ready
payload_matches 'BEFORE!'
verify
printf '0\n' > "$control/threads"
verify
[ "$(cat "$control/threads")" = 0 ]
started=0
touch "$lab/control/server.paused"
wait_file client.blocked
verify
[ "$(cat "$control/threads")" = 0 ]
payload_matches 'BEFORE!'
printf '%s\n' 'paused_fixture_bytes_unchanged=true'
verify
started=1
printf '1\n' > "$control/threads"
verify
[ "$(cat "$control/threads")" = 1 ]
payload_matches 'BEFORE!'
touch "$lab/control/server.restored"
wait_file client.complete
payload_matches 'AFTER!!'
printf '%s\n' 'explicit_restored_fixture_write_verified=true'
SERVER
after=$(cat /proc/fs/nfsd/threads)
printf 'host_threads_after=%s\n' "$after"
docker logs "$container_id"
if [ "$server_status" -ne 0 ] || [ "$after" != "$host_threads" ] ||
   [ "$(sha256sum /etc/exports | awk '{print $1}')" != "$host_exports" ] ||
   [ "$(sha256sum /var/lib/nfs/etab | awk '{print $1}')" != "$host_etab" ]; then
  printf '%s\n' 'status=blocked' 'Lab artifacts retained; no host correction or write retry.'
  for log in rpcbind mountd exportfs; do
    if [ -f "$lab/$log.log" ]; then
      printf 'Private lab log: %s\n' "$log"
      tail -n 12 "$lab/$log.log"
    fi
  done
  exit 2
fi
client_status=$(timeout 10s docker wait "$container_id")
[ "$client_status" = 0 ]
printf '%s\n' 'status=isolated_NFSv3_RPC_fixture_complete' \
  'Production exports/state unchanged; fixture artifacts retained.' \
  'No NFSv4, kernel-client cache, permanent denial or restart-inhibition claim.'
