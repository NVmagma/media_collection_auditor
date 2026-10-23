#!/usr/bin/env bash
# Invoked only by the launcher inside its new net/mount/PID namespaces.
set -euo pipefail
[ "$#" = 5 ] || exit 2
lab=$1; host_net=$2; host_mnt=$3; host_control=$4; private_net=$5
verify_namespaces(){
  [ "$(readlink /proc/self/ns/net)" = "$private_net" ] &&
  [ "$private_net" != "$host_net" ] &&
  [ "$(readlink /proc/self/ns/mnt)" != "$host_mnt" ] && [ "$$" = 1 ]
}
verify_namespaces
mount -n --bind "$lab/etc" /etc
mount -n -t tmpfs -o size=16m,nosuid,nodev tmpfs /var/lib
mount -n -t tmpfs -o size=8m,nosuid,nodev tmpfs /run
if [ "$(readlink -f /var/run)" != /run ]; then mount -n -t tmpfs -o size=8m,nosuid,nodev tmpfs /var/run; fi
mkdir -p /var/lib/nfs /var/lib/rpcbind /run/rpcbind /var/run/rpcbind
unset LISTEN_PID LISTEN_FDS LISTEN_FDNAMES
control=/proc/fs/nfsd
mount -n -t nfsd -o nosuid,nodev,noexec nfsd "$control"
thread_id=$(stat -Lc '%d:%i' "$control/threads")
version_id=$(stat -Lc '%d:%i' "$control/versions")
[ "$thread_id" != "$host_control" ] && [ "$(cat "$control/threads")" = 0 ]
verify(){
  verify_namespaces && [ "$(stat -f -c %t "$control")" = 6e667364 ] &&
  [ "$(stat -Lc '%d:%i' "$control/threads")" = "$thread_id" ] &&
  [ "$(stat -Lc '%d:%i' "$control/versions")" = "$version_id" ]
}
started=0
cleanup(){
  result=$?
  trap - EXIT
  if [ "$started" = 1 ]; then
    if verify && printf '0\n' > "$control/threads" && [ "$(cat "$control/threads")" = 0 ]; then :; else result=2; fi
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 2' INT TERM
verify
printf '%s\n' '-4' > "$control/versions"
versions=$(cat "$control/versions")
case " $versions " in *' +4'*|*' +2'*) exit 2;; esac
case " $versions " in *' +3 '*) :;; *) exit 2;; esac
# Existing Docker bridge interface only; no host interface/routing changes.
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
touch "$lab/control/ready"
marker=$(cat "$lab/data/.fixture-only")
wait_request(){
  for attempt in $(seq 1 8000); do
    if [ -f "$lab/control/$1.request" ]; then
      [ "$(cat "$lab/control/$1.request")" = "${marker##* }" ] || return 2
      return 0
    fi
    sleep 0.1
  done
  return 2
}
match_payload(){
  [ "$(sha256sum "$lab/data/payload.bin" | awk '{print $1}')" = "$(printf '%s\n' "$1" | sha256sum | awk '{print $1}')" ]
}
wait_request pause
match_payload 'BEFORE!'
pause_controller(){
  verify
  printf '0\n' > "$control/threads"
  verify
  [ "$(cat "$control/threads")" = 0 ]
  touch "$lab/control/pause-worker.ready"
  while :; do sleep 1; done
}
pause_controller &
worker=$!
for attempt in $(seq 1 100); do [ ! -f "$lab/control/pause-worker.ready" ] || break; sleep 0.1; done
[ -f "$lab/control/pause-worker.ready" ]
kill -KILL "$worker"
status=0
wait "$worker" 2>/dev/null || status=$?
[ "$status" = 137 ]
verify
[ "$(cat "$control/threads")" = 0 ]
started=0
match_payload 'BEFORE!'
touch "$lab/control/pause.ready"
wait_request observe
verify
[ "$(cat "$control/threads")" = 0 ]
match_payload 'BEFORE!'
touch "$lab/control/observe.ready"
wait_request restore
verify
[ "$(cat "$control/threads")" = 0 ]
match_payload 'BEFORE!'
started=1
printf '1\n' > "$control/threads"
verify
[ "$(cat "$control/threads")" = 1 ]
touch "$lab/control/restore.ready"
wait_request verify
for attempt in $(seq 1 300); do match_payload 'PENDING' && break; sleep 0.1; done
match_payload 'PENDING'
touch "$lab/control/verify.ready"
# Client sends finish only AFTER its successful fsync and clean unmount.
wait_request finish
verify
match_payload 'PENDING'
touch "$lab/control/finish.ready"
printf '%s\n' 'status=private_mac_nfs3_server_complete' 'paused_server_bytes_unchanged=true' 'controller_killed=true' 'explicit_recovery_write_observed=true'
