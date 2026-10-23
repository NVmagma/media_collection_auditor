#!/usr/bin/env bash
# Read-only client observation. No mount helpers, sudo, service or kernel changes.
set -euo pipefail
[ "$#" = 0 ] && [ "$(uname -s)" = Darwin ] || exit 2
printf '%s\n' 'read_only=true' 'production_activation=disabled' 'writer_exclusion_verified=false'
printf 'macos_version=%s\n' "$(sw_vers -productVersion)"
# Do not print server/export/user paths. Current options only, never originals.
nfsstat -m | awk '
/^[^[:space:]]/ { current=0 }
/Original mount options/ { current=0; next }
/Current mount parameters/ { current=1; count++; print "mount_index=" count; next }
current && /NFS parameters:/ {
  sub(/^.*NFS parameters:[[:space:]]*/, "")
  gsub(/,/, " ")
  for (i=1; i<=NF; i++)
    if ($i ~ /^(vers=[234]([.][0-9]+)?|tcp|udp|hard|soft|intr|nointr|resvport|noresvport|rsize=[0-9]+|wsize=[0-9]+|timeo=[0-9]+|retrans=[0-9]+|deadtimeout=[0-9]+)$/)
      print "current_option=" $i
}
END { print "mount_records_observed=" count+0 }
'
printf '%s\n' 'status=mac_client_options_observed' 'mounts_performed=false' 'kernel_settings_changed=false' 'Missing options remain unknown; this is not write-denial or recovery acceptance.'
