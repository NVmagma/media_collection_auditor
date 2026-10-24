#!/usr/bin/env bash
# Detached observations only. Never sources configuration or contacts share clients.
set -eu
[ "$#" -ge 1 ] || { echo 'Usage: bash SCRIPT EXISTING_DIRECTORY [EXISTING_ALIAS ...]' >&2; exit 2; }
# Validate all candidate arguments before collecting deployment metadata.
for candidate in "$@"; do
  case "$candidate" in /*) ;; *) echo 'Absolute existing directories required.' >&2; exit 2;; esac
  [[ ! "$candidate" =~ [[:cntrl:]] ]] || { echo 'Control characters refused.' >&2; exit 2; }
  [ -d "$candidate" ] && [ ! -L "$candidate" ] || { echo 'Existing nonsymlink directory required.' >&2; exit 2; }
  canonical=$(cd -P -- "$candidate" && pwd -P)
  [ "$canonical" = "$candidate" ] || { echo 'Canonical directory paths required; supply aliases separately.' >&2; exit 2; }
done
printf '%s\n' 'read_only=true' 'automatic_action=none' 'production_activation=disabled' \
  'production_authorized=false' 'private_location_verified=false' 'writer_exclusion_verified=false'
complete=true
for candidate in "$@"; do
  printf 'candidate_path=%q\n' "$candidate"
  if ! stat -Lc 'directory_identity=device:%d,inode:%i,mode:%a,uid:%u,gid:%g' -- "$candidate" 2>/dev/null; then
    echo 'directory_identity=unavailable'; complete=false
  fi
done
if command -v timeout >/dev/null 2>&1; then
  echo 'mount_topology_begin'
  if ! timeout 15s findmnt --list --noheadings --output TARGET,FSTYPE 2>/dev/null; then
    echo 'mount_topology=unavailable'; complete=false
  fi
  echo 'mount_topology_end'
  echo 'nfs_export_roots_begin'
  # Only root lines, not export options, clients or security settings.
  if exports=$(timeout 15s exportfs -v 2>/dev/null); then
    printf '%s\n' "$exports" | awk '/^\// {print $1}'
  else
    echo 'nfs_export_roots=unavailable'; complete=false
  fi
  echo 'nfs_export_roots_end'
  echo 'container_bind_sources_begin'
  if ids=$(timeout 15s docker ps -aq --no-trunc 2>/dev/null); then
    for id in $ids; do
      [[ "$id" =~ ^[0-9a-f]{64}$ ]] || { echo 'container_identity=unavailable'; complete=false; continue; }
      if ! timeout 15s docker inspect --type container --format \
'{{.Name}}{{range .Mounts}}{{if eq .Type "bind"}}
  bind_source={{json .Source}} writable={{.RW}}{{end}}{{end}}' "$id" 2>/dev/null; then
        echo 'container_binds=unavailable'; complete=false
      fi
    done
  else
    echo 'container_enumeration=unavailable'; complete=false
  fi
  echo 'container_bind_sources_end'
else
  echo 'bounded_observation_commands=unavailable'; complete=false
fi
echo 'potential_unraid_share_paths_begin'
# File names identify potential /mnt/user share roots, regardless of export status.
# No preference files are opened, sourced, or interpreted as commands.
shopt -s nullglob
configs=(/boot/config/shares/*.cfg)
if [ -d /boot/config/shares ] && [ -r /boot/config/shares ]; then
  for config in "${configs[@]}"; do
    name=${config##*/};name=${name%.cfg}
    printf 'potential_share_path=%q\n' "/mnt/user/$name"
  done
else
  echo 'potential_share_paths=unavailable'; complete=false
fi
echo 'potential_unraid_share_paths_end'
printf 'observation_commands_completed=%s\n' "$complete"
printf '%s\n' 'status=control_location_snapshot_review_required' \
  'Alias coverage, custom exports, ACLs, durability and concurrent changes remain unverified.' \
  'Potential share paths are not proof of an active export; absence is not proof of privacy.' \
  'No services, settings, mounts, media, runtime files or control artifacts were changed.'
