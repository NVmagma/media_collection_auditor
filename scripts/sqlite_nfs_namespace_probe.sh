#!/usr/bin/env bash
# Capability observation only. No NFSD control writes, exports or service calls.
# Creates ephemeral private mount/network namespaces and a read-only nfsd mount.
set -eu

printf '%s\n' 'production_activation=disabled' 'writer_exclusion_verified=false'
if [ "$#" -ne 0 ] || [ "$(uname -s)" != Linux ] || [ "$EUID" -ne 0 ]; then
  printf '%s\n' 'blocked=Linux_root_host_required_no_arguments' >&2
  exit 2
fi
for dependency in unshare timeout mount umount readlink mktemp rmdir cat awk; do
  if ! command -v "$dependency" >/dev/null 2>&1; then
    printf 'blocked=missing_dependency:%s\n' "$dependency" >&2
    exit 2
  fi
done
# Do not load a kernel module as a side effect of this probe.
if ! awk '$NF == "nfsd" { found=1 } END { exit !found }' /proc/filesystems; then
  printf '%s\n' 'blocked=nfsd_not_already_available' >&2
  exit 2
fi
host_threads=$(cat /proc/fs/nfsd/threads)
case "$host_threads" in ''|*[!0-9]*) printf '%s\n' 'blocked=unknown_host_threads' >&2; exit 2;; esac
host_net=$(readlink /proc/self/ns/net)
host_mnt=$(readlink /proc/self/ns/mnt)
scratch=$(mktemp -d /tmp/auditor-nfs-namespace.XXXXXX)
# Only remove our empty directory; never unmount anything in the host namespace.
trap 'rmdir -- "$scratch" 2>/dev/null || true' EXIT
printf 'host_threads_before=%s\n' "$host_threads"

probe_status=0
timeout --kill-after=5s 20s \
  unshare --net --mount --propagation private --fork \
  bash -eu -s -- "$scratch" "$host_net" "$host_mnt" <<'CHILD' || probe_status=$?
scratch=$1
host_net=$2
host_mnt=$3
current_net=$(readlink /proc/self/ns/net)
current_mnt=$(readlink /proc/self/ns/mnt)
if [ "$current_net" = "$host_net" ] || [ "$current_mnt" = "$host_mnt" ]; then
  printf '%s\n' 'blocked=namespace_identity_not_distinct' >&2
  exit 2
fi
printf '%s\n' 'network_namespace_distinct=true' 'mount_namespace_distinct=true'
# New namespace, new path, read-only control filesystem; no host mount reused.
mount -t nfsd -o ro,nosuid,nodev,noexec nfsd "$scratch"
trap 'umount -- "$scratch"' EXIT
isolated_threads=$(cat "$scratch/threads")
printf 'isolated_nfsd_threads=%s\n' "$isolated_threads"
if [ "$isolated_threads" != 0 ]; then
  printf '%s\n' 'blocked=unexpected_isolated_threads' >&2
  exit 2
fi
printf '%s\n' 'namespace_control_view_observed=true'
CHILD

after=$(cat /proc/fs/nfsd/threads)
printf 'host_threads_after=%s\n' "$after"
if [ "$probe_status" -ne 0 ] || [ "$after" != "$host_threads" ]; then
  printf '%s\n' 'status=blocked' 'No automatic service correction or retry is performed.'
  exit 2
fi
printf '%s\n' \
  'status=namespace_observation_complete' \
  'No server threads were started; no NFSD control file was written.' \
  'No service scripts, exports, network interfaces or production mounts were changed.' \
  'This does not verify client isolation, write denial or restart safety.'
