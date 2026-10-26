#!/usr/bin/env bash
# Selected-field observations only: never source scripts or invoke NFS controls.
set -u
if [ "$#" -ne 0 ]; then
  printf '%s\n' 'Usage: bash scripts/sqlite_nfs_restart_probe.sh' >&2
  exit 2
fi
printf '%s\n' \
  'read_only=true' 'production_activation=disabled' \
  'writer_exclusion_verified=false' 'restart_inhibition_verified=false' \
  'Upstream review revision: 26eb1b5c1d547ddbf44a38e63956ba24f659098b'

observe_preference(){
  local path=$1
  printf 'settings_file=%s\n' "$path"
  if [ ! -r "$path" ]; then
    printf '%s\n' 'shareNFSEnabled=unavailable'
    return
  fi
  # Only exact yes/no values are displayed; never dump another configuration key.
  awk '
    /^[[:space:]]*shareNFSEnabled[[:space:]]*=/ {
      count++
      if ($0 ~ /^shareNFSEnabled="(yes|no)"\r?$/) {
        value=$0; sub(/^shareNFSEnabled="/, "", value); sub(/"\r?$/, "", value)
      } else invalid=1
    }
    END {
      if (count == 1 && !invalid) print "shareNFSEnabled=" value
      else print "shareNFSEnabled=unverified"
    }' "$path"
}

observe_source(){
  local path=$1 expected=$2 observed digest
  printf '\nsource_file=%s\n' "$path"
  if [ ! -f "$path" ] || [ ! -r "$path" ]; then
    printf '%s\n' 'source_identity=unavailable'
    return
  fi
  if ! command -v sha256sum >/dev/null 2>&1; then
    printf '%s\n' 'source_identity=unverified'
    return
  fi
  if ! observed=$(sha256sum -- "$path" 2>/dev/null); then
    printf '%s\n' 'source_identity=unverified'
    return
  fi
  digest=${observed%% *}
  printf 'sha256=%s\n' "$digest"
  if [ "$digest" = "$expected" ]; then
    printf '%s\n' 'matches_reviewed_upstream=true'
  else
    printf '%s\n' 'matches_reviewed_upstream=false'
  fi
}

observe_preference /boot/config/share.cfg
observe_preference /var/local/emhttp/var.ini
observe_source /usr/local/etc/rc.d/rc.nfsd a2e6f7396e688a9dfbbe35e0f35c5839f1ee0a606b46ca1047bfa0b10e646fcf
observe_source /etc/rc.d/rc.runlog 70cb99b67bba06c3502ad071d8be13b10780d05c76c50cf2839c619846a8020d
observe_source /etc/rc.d/rc.library.source cad384311906870c88adca7f7a8b4f6253ab30620189367e493348bb7e9622e8
observe_source /usr/local/emhttp/plugins/dynamix/scripts/nfsSettings e7c0ad009544cea2cf204876acf35bb89ac3b4974d838e8a158645ac90c4532b
observe_source /usr/local/emhttp/plugins/dynamix/scripts/reload_services e4e944ece1006bfbb1afeb79d203d374b2a37b979e4bc027787673dfe3af07a7
observe_source /usr/local/emhttp/plugins/dynamix/NFS.page ec479bd125ec4eac5218a1eb4bb782d8c93aafe779fa7a0c446fca559fc477d9
# Boot sources are hashed only; never run or source a boot script, including go.
observe_source /etc/rc.d/rc.S 4b8b3a2c9a0319a5122567e2f434050073bf672a06d4ab4998ffab3afd92c38a
observe_source /etc/rc.d/rc.M 77d4b4c81b5718c5a5d902667e120fca37f78d9a69c2a953bbdd48c05574b96f
observe_source /etc/rc.d/rc.inet2 dcc7b06d06c7e6aa17949d5ef3cb0396d7f9bf9afb9eec4f090d9b406c3042f9
observe_source /etc/rc.d/rc.local 96d61ef181addb26e8d407b4b981cd0951d8a919357441f330567296f7df5813
printf '\n%s\n' \
  'Matching source identifies reviewed bytes; it does not establish a restart fence.' \
  'No helpers/configuration were sourced; no status/start/stop/update calls were made.' \
  'Custom startup jobs, boot ordering and direct privileged bypasses remain unverified.'
