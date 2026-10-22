#!/usr/bin/env bash
# Host-only read-only discovery for the proposed full-NFS maintenance adapter.
# Never sources service/config files or invokes a service control command.
set -u

if [ "$#" -ne 0 ]; then
  printf '%s\n' 'Usage: bash scripts/sqlite_nfs_pause_probe.sh' >&2
  exit 2
fi

printf '%s\n' \
  'read_only=true' \
  'production_activation=disabled' \
  'writer_exclusion_verified=false' \
  'Snapshot only; no stop/start/reload/export commands are executed.'

printf '\n%s\n' 'Selected host version:'
if [ -r /etc/unraid-version ]; then
  awk '/^version="[0-9][0-9A-Za-z.+_-]*"$/ { print; found=1 }
       END { if (!found) print "unraid_version=unverified" }' /etc/unraid-version
else
  printf '%s\n' 'unraid_version=unavailable'
fi

printf '\n%s\n' 'Kernel NFS service observations:'
for field in threads versions; do
  observed_file="/proc/fs/nfsd/$field"
  if [ -r "$observed_file" ]; then
    # Numeric/version tokens only; never dump arbitrary configuration contents.
    if [ "$field" = threads ]; then
      awk '/^[0-9]+$/ { print "nfsd_threads=" $0; found=1 }
           END { if (!found) print "nfsd_threads=unverified" }' "$observed_file"
    else
      awk '/^[+0-9. -]+$/ { print "nfsd_versions=" $0; found=1 }
           END { if (!found) print "nfsd_versions=unverified" }' "$observed_file"
    fi
  else
    printf '%s\n' "nfsd_$field=unavailable"
  fi
done

printf '\n%s\n' 'Candidate service-control file identities (not executed or sourced):'
for candidate in /etc/rc.d/rc.nfsd /usr/local/etc/rc.d/rc.nfsd; do
  if [ -f "$candidate" ] && [ -r "$candidate" ]; then
    printf 'candidate=%s\n' "$candidate"
    if command -v readlink >/dev/null 2>&1; then
      readlink -f -- "$candidate" 2>/dev/null || printf '%s\n' 'canonical_path=unverified'
    else
      printf '%s\n' 'canonical_path=unavailable'
    fi
    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum -- "$candidate" 2>/dev/null || printf '%s\n' 'service_digest=unverified'
    else
      printf '%s\n' 'service_digest=unavailable'
    fi
  else
    printf 'candidate=%s unavailable\n' "$candidate"
  fi
done

printf '\n%s\n' \
  'Run on the Unraid host, not inside the auditor container.' \
  'A zero thread count, missing interface or matching digest is not an ownership permit.' \
  'Existing clients, restart controls and non-NFS writers remain unverified.'
