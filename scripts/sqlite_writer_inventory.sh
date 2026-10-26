#!/usr/bin/env bash
# Read-only Unraid deployment discovery. No service or configuration changes.
set -u

share_name=${1:-media_storage}
if [ "$#" -gt 1 ] || [[ ! "$share_name" =~ ^[a-zA-Z0-9_.-]+$ ]] || [ "$share_name" = . ] || [ "$share_name" = .. ]; then
  printf '%s\n' 'Usage: bash scripts/sqlite_writer_inventory.sh SIMPLE_SHARE_NAME' >&2
  exit 2
fi

printf '%s\n' \
  'read_only=true' \
  'writer_exclusion_verified=false' \
  'production_activation=disabled' \
  'Snapshot only: stopped containers, aliases, host jobs and share clients still require review.'

printf '\n%s\n' 'Container mounts and restart/admin access metadata:'
if command -v docker >/dev/null 2>&1; then
  if container_ids=$(docker ps -aq 2>/dev/null); then
    if [ -z "$container_ids" ]; then
      printf '%s\n' 'No containers observed; this does not establish writer exclusion.'
    fi
    for container_id in $container_ids; do
      if ! docker inspect --type container --format \
'{{.Name}} running={{.State.Running}} paused={{.State.Paused}} restart={{.HostConfig.RestartPolicy.Name}} privileged={{.HostConfig.Privileged}} pid_mode={{.HostConfig.PidMode}} cap_add={{json .HostConfig.CapAdd}}
{{range .Mounts}}  {{.Type}} {{json .Source}} -> {{json .Destination}} writable={{.RW}}
{{end}}' "$container_id" 2>/dev/null; then
        printf '%s\n' 'Container inspection unavailable; inventory is incomplete.'
      fi
    done
  else
    printf '%s\n' 'Container enumeration unavailable; inventory is incomplete.'
  fi
else
  printf '%s\n' 'Docker CLI unavailable; inventory is incomplete.'
fi

printf '\n%s\n' 'Selected Unraid share exposure settings (observations, not exclusion proof):'
share_config="/boot/config/shares/${share_name}.cfg"
if [ -r "$share_config" ]; then
  awk '/^(shareExport|shareSecurity|shareExportNFS|shareSecurityNFS)=/ { print; found=1 }
       END { if (!found) print "Selected share settings unavailable; exposure remains unverified." }' "$share_config"
else
  printf '%s\n' 'Share configuration unavailable; exposure remains unverified.'
fi
printf '\n%s\n' \
  'Host job names/schedulers and share protocols must be supplied by the operator.' \
  'Do not paste raw cron commands, environment dumps, credentials or full Docker inspect JSON.' \
  'No writers were stopped, paused, remounted or reconfigured.'
