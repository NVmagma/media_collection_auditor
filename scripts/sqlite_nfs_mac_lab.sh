#!/usr/bin/env bash
# Tower: private bridge NFSD instance; no host exports/controls, modules or ports.
set -euo pipefail
umask 077
[ "$#" = 1 ] && [ "$(uname -s)" = Linux ] && [ "$EUID" = 0 ] || exit 2
parent=$1
case "$parent" in /*) :;; *) exit 2;; esac
case "$parent" in *[!a-zA-Z0-9_./-]*) exit 2;; esac
[ -d "$parent" ] && [ "$(readlink -f "$parent")" = "$parent" ]
for tool in docker nsenter unshare timeout mount readlink stat ip rpcbind rpc.mountd rpcinfo exportfs sha256sum; do command -v "$tool" >/dev/null; done
awk '$NF=="nfsd" {found=1} END {exit !found}' /proc/filesystems
# Refuse missing prerequisites rather than asking the kernel to load them.
for module in nfsd sunrpc lockd; do [ -d "/sys/module/$module" ] || { printf 'blocked=module_not_already_present:%s\n' "$module"; exit 2; }; done
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
image=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
docker image inspect "$image" >/dev/null
host_net=$(readlink /proc/self/ns/net)
host_mnt=$(readlink /proc/self/ns/mnt)
host_control=$(stat -Lc '%d:%i' /proc/fs/nfsd/threads)
host_threads=$(cat /proc/fs/nfsd/threads)
case "$host_threads" in ''|*[!0-9]*) exit 2;; esac
snapshot(){
  sha256sum /etc/exports /var/lib/nfs/etab /usr/local/etc/rc.d/rc.nfsd /boot/config/share.cfg
  cat /proc/fs/nfsd/versions /proc/fs/nfsd/portlist
  timeout 10 rpcinfo -p 127.0.0.1
  awk '{print $1}' /proc/modules | sort
}
before=$(snapshot)
lab=$(mktemp -d "$parent/nfs-mac.XXXXXX")
mkdir "$lab/control" "$lab/data" "$lab/etc"
nonce=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
printf 'DISPOSABLE MAC NFS FIXTURE %s\n' "$nonce" > "$lab/data/.fixture-only"
printf 'INITIAL\n' > "$lab/data/payload.bin"
chmod 0755 "$lab/data"
chmod 0644 "$lab/data/.fixture-only"
chmod 0666 "$lab/data/payload.bin"
for item in netconfig services passwd group nsswitch.conf hosts; do
  [ ! -r "/etc/$item" ] || cp -- "/etc/$item" "$lab/etc/$item"
done
printf '[general]\nstate-directory-path=/var/lib/nfs\n' > "$lab/etc/nfs.conf"
id=''; server=''; net_fd=''
label="nfs-mac-${lab##*.}"
ours(){
  case "$id" in ''|*[!0-9a-f]*) return 1;; esac
  [ "${#id}" = 64 ] && [ "$(timeout 10 docker inspect --format '{{index .Config.Labels "org.nvmagma.auditor.fixture"}}' "$id")" = "$label" ]
}
cleanup(){
  if [ -n "$server" ]; then
    # Only signal a still-running child job, never a reaped/reused numeric PID.
    if jobs -pr | awk -v wanted="$server" '$1==wanted {found=1} END {exit !found}'; then
      kill "$server" 2>/dev/null || :
    fi
    wait "$server" 2>/dev/null || :
    server=''
  fi
  if [ -n "$id" ]; then ours && timeout --kill-after=5s 20 docker rm -f "$id" >/dev/null || return 1; id=''; fi
  if [ -n "$net_fd" ]; then exec {net_fd}<&-; net_fd=''; fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
id=$(timeout 20 docker create --pull never --network bridge --read-only --cap-drop ALL --security-opt no-new-privileges --restart no --memory 64m --pids-limit 32 --cpus 0.25 --label "org.nvmagma.auditor.fixture=$label" "$image" python -B -c 'import time; time.sleep(900)')
ours
timeout 15 docker start "$id" >/dev/null
pid=$(timeout 10 docker inspect --format '{{.State.Pid}}' "$id")
case "$pid" in ''|*[!0-9]*|0) exit 2;; esac
exec {net_fd}<"/proc/$pid/ns/net"
private_net=$(readlink "/proc/self/fd/$net_fd")
[ "$private_net" != "$host_net" ]
ours
[ "$(timeout 10 docker inspect --format '{{.State.Pid}}' "$id")" = "$pid" ]
address=$(timeout 10 docker inspect --format '{{(index .NetworkSettings.Networks "bridge").IPAddress}}' "$id")
gateway=$(timeout 10 docker inspect --format '{{(index .NetworkSettings.Networks "bridge").Gateway}}' "$id")
for value in "$address" "$gateway"; do
  [[ "$value" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 2
done
# Only SSH-forwarded traffic from the bridge gateway; no wildcard client export.
printf '%s %s(rw,sync,no_subtree_check,all_squash,anonuid=65534,anongid=65534,insecure,fsid=28174)\n' "$lab/data" "$gateway" > "$lab/etc/exports"
printf 'production_activation=disabled\nwriter_exclusion_verified=false\nLab directory: %s\n' "$lab"
timeout --kill-after=5s 850 nsenter --net="/proc/self/fd/$net_fd" \
  unshare --mount --pid --fork --kill-child --mount-proc --propagation private \
  bash "$repo/scripts/sqlite_nfs_mac_server.sh" "$lab" "$host_net" "$host_mnt" "$host_control" "$private_net" > "$lab/server.log" 2>&1 &
server=$!
for attempt in $(seq 1 200); do
  [ ! -f "$lab/control/ready" ] || break
  kill -0 "$server" || { printf 'private_server_failed_log=%s/server.log\n' "$lab"; exit 2; }
  sleep 0.1
done
[ -f "$lab/control/ready" ]
printf 'fixture_ready=true\nfixture_address=%s\nfixture_export=%s/data\nfixture_nonce=%s\nremote_phase_script=%s/scripts/sqlite_nfs_mac_phase.sh\nlifetime_seconds=850\n' "$address" "$lab" "$nonce" "$repo"
printf '\nRun in a SECOND terminal on the Mac (leave this Tower terminal open):\n'
printf 'mac_driver=$(mktemp -t auditor-nfs-client)\n'
printf 'ssh root@10.0.0.10 %q > "$mac_driver" &&\n' "cat '$repo/scripts/sqlite_nfs_mac_client.py'"
printf 'python3 "$mac_driver" --address %q --lab %q --nonce %q --phase-script %q\n\n' "$address" "$lab" "$nonce" "$repo/scripts/sqlite_nfs_mac_phase.sh"
printf '%s\n' 'Keep this terminal open. Only new fixture state is active. Use the Mac driver through SSH; no host ports are published.'
wait "$server"
server=''
[ -f "$lab/control/finish.ready" ]
cleanup
trap - EXIT
[ "$(cat /proc/fs/nfsd/threads)" = "$host_threads" ]
[ "$(snapshot)" = "$before" ]
printf '%s\n' 'status=isolated_mac_nfs3_fixture_complete' 'host_snapshot_unchanged=true' 'module_loads_performed=false' 'restart_inhibition_verified=false' 'production_authorized=false'
