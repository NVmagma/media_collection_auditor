#!/bin/bash
# Sourced only by the verified private NFSD supervisor; never a host installer.
if [ "${scenario:-}" != restart-guard ] || [ "$$" != 1 ] ||
   ! declare -F verify >/dev/null || ! verify; then
  printf '%s\n' 'blocked=private_supervisor_required' >&2
  return 2 2>/dev/null || exit 2
fi

prepare_restart_guard(){
  verify
  # Reviewed settings apply writes here; queue tools must not see host spools.
  mount -n -t tmpfs -o size=8m,nosuid,nodev tmpfs /boot
  mount -n -t tmpfs -o size=8m,nosuid,nodev tmpfs /var/spool
  mkdir -p /boot/config/default /etc/default /etc/rc.d "$lab/fixture-bin"
  printf 'RPC_NFSD_VERS="-N 4"\nRPC_NFSD_COUNT="8"\n' > /etc/default/nfs
  cp -- "$lab/reviewed/rc.runlog" /etc/rc.d/rc.runlog
  # Other services are inert fixtures; only NFS dispatch is exercised.
  printf '#!/bin/bash -p\nexit 0\n' > "$lab/fixture-noop"
  chmod 0555 "$lab/fixture-noop"
  for service in rpc ntpd nginx sshd avahidaemon samba; do
    cp -- "$lab/fixture-noop" "/etc/rc.d/rc.$service"
  done
  # Keep the reviewed logger helper from sending fixture messages to host syslog.
  mount -n --bind "$lab/fixture-noop" /usr/bin/logger
  for target in /etc/rc.d/rc.nfsd /usr/local/etc/rc.d/rc.nfsd; do
    if [ "$target" = /etc/rc.d/rc.nfsd ]; then : > "$target"; fi
    mount -n --bind "$lab/restart-guard.sh" "$target"
    mount -n -o remount,bind,ro,nosuid,nodev "$target"
  done
  printf '#!/bin/bash -p\nprintf "1 fixture-queue\\n"\n' > "$lab/fixture-bin/atq"
  cat > "$lab/fixture-bin/atrm" <<'QUEUE'
#!/bin/bash -p
[ "$#" = 1 ] && [ "$1" = 1 ] || exit 2
printf 'FIXTURE ONLY\n' > "$NFS_LAB_QUEUE_MARKER"
QUEUE
  chmod 0555 "$lab/fixture-bin/atq" "$lab/fixture-bin/atrm"
  verify
}

exercise_restart_entrypoints(){
  verify
  [ "$(cat "$control/threads")" = 0 ]
  expected=$(sha256sum "$lab/restart-guard.sh" | awk '{print $1}')
  for target in /etc/rc.d/rc.nfsd /usr/local/etc/rc.d/rc.nfsd; do
    [ "$(sha256sum "$target" | awk '{print $1}')" = "$expected" ]
    for operation in start restart update reload status stop; do
      result=0
      "$target" "$operation" 2>> "$lab/guard-attempts.log" || result=$?
      [ "$result" = 75 ]
      verify
      [ "$(cat "$control/threads")" = 0 ]
    done
  done
  printf '%s\n' 'guarded_service_dispatches_denied=12'
  # Actual reviewed settings script; its default edits hit private /boot only.
  bash -p "$lab/reviewed/nfsSettings" apply '-N 4' 8 > "$lab/settings-apply.log" 2>&1
  [ -f /boot/config/default/nfs ]
  grep -q '^RPC_NFSD_COUNT="8"$' /boot/config/default/nfs
  grep -q 'NFS service dispatch denied by maintenance guard' "$lab/settings-apply.log"
  verify
  [ "$(cat "$control/threads")" = 0 ]
  # Actual reload dispatcher, fixture queue and inert unrelated service scripts.
  PATH="$lab/fixture-bin:$PATH" NFS_LAB_QUEUE_MARKER="$lab/control/fixture-queue-seen" \
    bash -p "$lab/reviewed/reload_services" > "$lab/network-update.log" 2>&1
  [ -f "$lab/control/fixture-queue-seen" ]
  # reload_services intentionally suppresses dispatcher stderr; verify result
  # independently rather than trusting its successful exit status.
  verify
  [ "$(cat "$control/threads")" = 0 ]
  printf '%s\n' 'reviewed_settings_apply_left_threads_zero=true' \
    'reviewed_network_update_left_threads_zero=true'
}
