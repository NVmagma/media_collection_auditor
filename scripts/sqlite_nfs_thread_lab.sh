#!/usr/bin/env bash
# Bounded NFSD thread control in disposable private namespaces; NO exports.
set -eu
printf '%s\n' 'production_activation=disabled' 'writer_exclusion_verified=false'
if [ "$#" -ne 0 ] || [ "$(uname -s)" != Linux ] || [ "$EUID" -ne 0 ]; then
  printf '%s\n' 'blocked=Linux_root_host_required_no_arguments' >&2
  exit 2
fi
for dependency in unshare timeout mount umount readlink mktemp rmdir cat awk stat; do
  command -v "$dependency" >/dev/null 2>&1 || { printf 'blocked=missing:%s\n' "$dependency" >&2; exit 2; }
done
if ! awk '$NF == "nfsd" { found=1 } END { exit !found }' /proc/filesystems; then
  printf '%s\n' 'blocked=nfsd_not_already_available' >&2
  exit 2
fi
host_threads=$(cat /proc/fs/nfsd/threads)
case "$host_threads" in ''|*[!0-9]*) printf '%s\n' 'blocked=unknown_host_threads' >&2; exit 2;; esac
host_net=$(readlink /proc/self/ns/net)
host_mnt=$(readlink /proc/self/ns/mnt)
host_control=$(stat -Lc '%d:%i' /proc/fs/nfsd/threads)
scratch=$(mktemp -d /tmp/auditor-nfs-threads.XXXXXX)
trap 'rmdir -- "$scratch" 2>/dev/null || true' EXIT
printf 'host_threads_before=%s\n' "$host_threads"
lab_status=0
timeout --kill-after=5s 30s \
  unshare --net --mount --propagation private --fork \
  bash -eu -s -- "$scratch" "$host_net" "$host_mnt" "$host_control" <<'CHILD' || lab_status=$?
scratch=$1
host_net=$2
host_mnt=$3
host_control=$4
distinct_namespaces(){
  [ "$(readlink /proc/self/ns/net)" != "$host_net" ] &&
    [ "$(readlink /proc/self/ns/mnt)" != "$host_mnt" ]
}
if ! distinct_namespaces; then
  printf '%s\n' 'blocked=namespace_identity_not_distinct' >&2
  exit 2
fi
mount -t nfsd -o nosuid,nodev,noexec nfsd "$scratch"
started=0
bound=0
verify_control(){
  distinct_namespaces && [ "$bound" = 1 ] &&
    [ "$(stat -f -c %t "$scratch")" = 6e667364 ] &&
    [ "$(stat -Lc '%d:%i' "$scratch/threads")" = "$thread_identity" ] &&
    [ "$(stat -Lc '%d:%i' "$scratch/versions")" = "$version_identity" ]
}
cleanup(){
  result=$?
  trap - EXIT
  if [ "$started" = 1 ]; then
    # Never fall back to /proc/fs/nfsd or any host control/service command.
    if verify_control && printf '0\n' > "$scratch/threads" &&
        [ "$(cat "$scratch/threads")" = 0 ]; then
      printf '%s\n' 'private_cleanup_threads=0'
    else
      printf '%s\n' 'blocked=private_cleanup_unverified' >&2
      result=2
    fi
  fi
  if ! umount -- "$scratch"; then result=2; fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 2' INT TERM
thread_identity=$(stat -Lc '%d:%i' "$scratch/threads")
version_identity=$(stat -Lc '%d:%i' "$scratch/versions")
if [ "$thread_identity" = "$host_control" ] || [ "$(cat "$scratch/threads")" != 0 ]; then
  printf '%s\n' 'blocked=control_view_not_new_and_idle' >&2
  exit 2
fi
bound=1
verify_control
# Avoid the NFSv4 recovery/upcall path and any persistent recovery directory.
# No rpcbind/mountd is launched, no interface is enabled, and no export is added.
printf '%s\n' '-4' > "$scratch/versions"
versions=$(cat "$scratch/versions")
case " $versions " in *' +4'*|*' +2'*) printf '%s\n' 'blocked=unexpected_protocols' >&2; exit 2;; esac
case " $versions " in *' +3 '*) :;; *) printf '%s\n' 'blocked=NFSv3_unavailable' >&2; exit 2;; esac
printf 'isolated_versions=%s\n' "$versions"
for cycle in 1 2; do
  verify_control
  started=1  # Cleanup is required even if the following write has an uncertain result.
  printf '1\n' > "$scratch/threads"
  verify_control
  running=$(cat "$scratch/threads")
  printf 'cycle=%s isolated_running_threads=%s\n' "$cycle" "$running"
  [ "$running" = 1 ]
  verify_control
  printf '0\n' > "$scratch/threads"
  verify_control
  stopped=$(cat "$scratch/threads")
  printf 'cycle=%s isolated_stopped_threads=%s\n' "$cycle" "$stopped"
  [ "$stopped" = 0 ]
  started=0
done
CHILD
after=$(cat /proc/fs/nfsd/threads)
printf 'host_threads_after=%s\n' "$after"
if [ "$lab_status" -ne 0 ] || [ "$after" != "$host_threads" ]; then
  printf '%s\n' 'status=blocked' 'No host service correction or retry is performed.'
  exit 2
fi
printf '%s\n' \
  'status=isolated_thread_cycles_complete' \
  'No exports, client mounts, host service scripts or production control files were changed.' \
  'This does not verify real client write denial, NFSv4 recovery or restart inhibition.'
