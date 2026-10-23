#!/bin/bash
# Selected read-only observations. Never source settings or execute service helpers.
set -euo pipefail
root=${1:-/}
root=$(realpath -e -- "$root")
[[ -d "$root" && ! "$root" =~ [[:space:]\\] ]] || exit 1
printf 'read_only=true\nproduction_activation=disabled\nproduction_authorized=false\nwriter_exclusion_verified=false\nrestart_inhibition_verified=false\nautomatic_action=none\n'
preference() {
  local relative=$1 key=$2 result
  if [[ ! -f "$root/$relative" ]]; then result=unavailable
  else
    result=$(timeout 5s head -c 1048577 -- "$root/$relative" | awk -v key="$key" '
      { bytes+=length($0)+1 }
      $0 ~ "^[[:space:]]*(export[[:space:]]+)?" key "[[:space:]]*=" {
        count++
        if ($0==key "=\"yes\"") value="yes"
        else if ($0==key "=\"no\"") value="no"
        else value="unverified"
      }
      END { if(bytes>1048576 || count!=1) print "unverified"; else print value }
    ') || result=unavailable
  fi
  printf 'setting=%s key=%s observed=%s\n' "/$relative" "$key" "$result"
}
preference boot/config/share.cfg shareSMBEnabled
preference boot/config/share.cfg shareNFSEnabled
preference boot/config/docker.cfg DOCKER_ENABLED
for relative in etc/rc.d/rc.samba usr/local/etc/rc.d/rc.samba usr/local/sbin/mover usr/local/sbin/mover.old; do
  value=unavailable
  if [[ -f "$root/$relative" ]]; then
    value=$(timeout 5s sha256sum -- "$root/$relative") || value=unavailable
    value=${value%% *}
    [[ "$value" =~ ^[0-9a-f]{64}$ ]] || value=unavailable
  fi
  printf 'source=/%s sha256=%s\n' "$relative" "$value"
done
for relative in etc/cron.d/root etc/cron.d/mover var/spool/cron/crontabs/root; do
  value=unavailable
  if [[ -f "$root/$relative" ]]; then
    value=$(timeout 5s head -c 1048577 -- "$root/$relative" | awk '
      { bytes+=length($0)+1 }
      /^[[:space:]]*($|#)/ { next }
      { active++; if($0 ~ /(^|[\/[:space:]])mover([.[:space:]]|$)/) mover++ }
      END { if(bytes>1048576) print "unverified"; else printf "active_entries=%d mover_mentions=%d",active,mover }
    ') || value=unavailable
  fi
  printf 'schedule=/%s %s\n' "$relative" "$value"
done
for process in smbd nmbd mover mover.old; do
  observed=not_collected_for_fixture
  if [[ "$root" = / ]]; then
    observed=unknown
    if command -v pgrep >/dev/null 2>&1; then
      if pgrep -x "$process" >/dev/null 2>&1; then observed=observed
      else case "$?" in 1) observed=not_observed;; esac
      fi
    fi
  fi
  printf 'process=%s status=%s\n' "$process" "$observed"
done
printf 'status=host_writer_scope_review_required\n'
printf 'Snapshot only; process absence and preference values do not establish a fence.\n'
printf 'No cron commands, service helpers, settings handlers or module controls were executed.\n'
