#!/usr/bin/env bash
# Read-only prerequisites. Never mount, load modules or invoke NFS helpers.
set -euo pipefail
if [ "$#" != 0 ] || [ "$(uname -s)" != Linux ]; then
  printf '%s\n' 'Usage: bash scripts/sqlite_nfs_kernel_client_probe.sh (Linux host; no arguments)' >&2
  exit 2
fi
printf '%s\n' 'read_only=true' 'production_activation=disabled' \
  'production_authorized=false' 'writer_exclusion_verified=false' \
  'restart_inhibition_verified=false'
release=$(uname -r)
case "$release" in ''|*[!0-9A-Za-z._+-]*) printf '%s\n' 'kernel_release=unverified';;
  *) printf 'kernel_release=%s\n' "$release";; esac

observe_filesystem(){
  local path=$1 name=$2
  if [ ! -r "$path" ]; then
    printf 'filesystem_%s=unavailable\n' "$name"
  elif awk -v wanted="$name" '$NF == wanted { found=1 } END { exit !found }' "$path"; then
    printf 'filesystem_%s=registered\n' "$name"
  else
    printf 'filesystem_%s=not_registered\n' "$name"
  fi
}

observe_boolean(){
  local path=$1 name=$2 value
  if [ ! -r "$path" ]; then
    printf '%s=unavailable\n' "$name"
    return
  fi
  if ! value=$(cat -- "$path" 2>/dev/null); then
    printf '%s=unavailable\n' "$name"
    return
  fi
  case "$value" in Y|N|0|1) printf '%s=%s\n' "$name" "$value";;
    *) printf '%s=unverified\n' "$name";; esac
}

select_config(){
  awk '/^(CONFIG_NFS_FS|CONFIG_NFS_V4|CONFIG_NFS_V4_1|CONFIG_NFS_V4_2|CONFIG_NFS_LOCALIO|CONFIG_NFSD|CONFIG_NFSD_V4)=(y|m|n)$/ || /^# (CONFIG_NFS_FS|CONFIG_NFS_V4|CONFIG_NFS_V4_1|CONFIG_NFS_V4_2|CONFIG_NFS_LOCALIO|CONFIG_NFSD|CONFIG_NFSD_V4) is not set$/'
}

observe_filesystem /proc/filesystems nfs
observe_filesystem /proc/filesystems nfs4
observe_filesystem /proc/filesystems nfsd
observe_boolean /sys/module/nfs/parameters/localio_enabled localio_enabled
observe_boolean /sys/module/nfs/parameters/localio_O_DIRECT_semantics localio_direct_semantics
helper=$(type -P mount.nfs || true)
if [ -n "$helper" ] && [ -f "$helper" ] && [ -x "$helper" ]; then
  printf 'mount_helper_path=%s\n' "$helper"
  if command -v sha256sum >/dev/null 2>&1; then
    if digest=$(sha256sum -- "$helper" 2>/dev/null); then
      printf 'mount_helper_sha256=%s\n' "${digest%% *}"
    else printf '%s\n' 'mount_helper_identity=unavailable'; fi
  else printf '%s\n' 'mount_helper_identity=unavailable'; fi
else
  printf '%s\n' 'mount_helper_path=unavailable'
fi
if [ -r /proc/config.gz ] && command -v zcat >/dev/null 2>&1; then
  if selected=$(zcat /proc/config.gz 2>/dev/null | select_config); then
    printf '%s\n' 'kernel_config_source=/proc/config.gz'
    if [ -n "$selected" ]; then printf '%s\n' "$selected";
    else printf '%s\n' 'selected_kernel_config=unavailable'; fi
  else printf '%s\n' 'selected_kernel_config=unavailable'; fi
else
  printf '%s\n' 'selected_kernel_config=unavailable'
fi
printf '%s\n' 'kernel_mounts_performed=false' 'module_loads_performed=false' \
  'status=kernel_client_prerequisites_observed' \
  'Missing parameters/configuration are unknown capabilities, not a disabled-LOCALIO claim.' \
  'No NFS helpers/configuration were executed or sourced; no production NFS controls were changed.'
