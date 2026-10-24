#!/bin/bash
# Selected read-only observations. Never source settings or execute service helpers.
set -euo pipefail
root=${1:-/}
root=$(realpath -e -- "$root")
[[ -d "$root" && ! "$root" =~ [[:space:]\\] ]] || exit 1
printf 'read_only=true\nproduction_activation=disabled\nproduction_authorized=false\nwriter_exclusion_verified=false\nrestart_inhibition_verified=false\nautomatic_action=none\nreviewed_unraid_revision=26eb1b5c1d547ddbf44a38e63956ba24f659098b\n'
preference() {
  local relative=$1 key=$2 result
  if [[ ! -f "$root/$relative" ]]; then result=unavailable
  else
    result=$(timeout 5s head -c 1048577 -- "$root/$relative" | awk -v key="$key" '
      { bytes+=length($0)+1; line=$0; if(sub(/\r$/,"",line)) crlf++ }
      line ~ "^[[:space:]]*(export[[:space:]]+)?" key "[[:space:]]*=" {
        count++
        if (line==key "=\"yes\"" || line==key "=yes") value="yes"
        else if (line==key "=\"no\"" || line==key "=no") value="no"
        else value="unverified"
      }
      END {
        if(bytes>1048576 || count!=1) value="unverified"
        printf "%s assignments=%d terminal_cr_lines=%d\n",value,count,crlf
      }
    ') || result=unavailable
  fi
  printf 'setting=%s key=%s observed=%s\n' "/$relative" "$key" "$result"
}
preference boot/config/share.cfg shareSMBEnabled
preference boot/config/share.cfg shareNFSEnabled
preference boot/config/docker.cfg DOCKER_ENABLED
for relative in etc/rc.d/rc.samba usr/local/etc/rc.d/rc.samba usr/local/sbin/mover usr/local/sbin/mover.old usr/libexec/unraid/move; do
  value=unavailable
  if [[ -f "$root/$relative" ]]; then
    value=$(timeout 5s sha256sum -- "$root/$relative") || value=unavailable
    value=${value%% *}
    [[ "$value" =~ ^[0-9a-f]{64}$ ]] || value=unavailable
  fi
  expected=unknown
  case "$relative" in
    etc/rc.d/rc.samba|usr/local/etc/rc.d/rc.samba) expected=3167690b93a05c223179c15679604931ac3aa96c3365c1131aa00f399a93ffee;;
    usr/local/sbin/mover) expected=def6b33c2f8f4c8e85a93dd18dd6179234e05730d8cecfe292d6a3c416ec29fc;;
    usr/local/sbin/mover.old) expected=a7bf8bc106faf2b16714a5ab22db26c73397322d7ff11a7c09a1296f741e9548;;
  esac
  matches=unverified
  if [[ "$expected" != unknown && "$value" != unavailable ]]; then
    matches=false
    [[ "$value" != "$expected" ]] || matches=true
  fi
  printf 'source=/%s sha256=%s matches_reviewed_unraid=%s\n' "$relative" "$value" "$matches"
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
for process in smbd nmbd winbindd wsdd2 mover mover.old move; do
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
