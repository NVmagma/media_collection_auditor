#!/usr/bin/env bash
# Fixed fixture marker requests only, no NFS/service controls or arbitrary actions.
set -euo pipefail
[ "$#" = 3 ] || exit 2
lab=$1; nonce=$2; phase=$3
case "$lab" in /*/nfs-mac.*) :;; *) exit 2;; esac
case "$lab" in *[!a-zA-Z0-9_./-]*|*/../*) exit 2;; esac
case "$nonce" in ''|*[!0-9a-f]*) exit 2;; esac
[ "${#nonce}" = 32 ]
[ "$(cat "$lab/data/.fixture-only")" = "DISPOSABLE MAC NFS FIXTURE $nonce" ]
case "$phase" in pause|observe|restore|verify|finish) :;; *) exit 2;; esac
case "$phase" in
  pause) previous=ready;;
  observe) previous=pause.ready;;
  restore) previous=observe.ready;;
  verify) previous=restore.ready;;
  finish) previous=verify.ready;;
esac
[ -f "$lab/control/$previous" ]
# Request replay is rejected rather than implicitly retrying an uncertain phase.
(set -o noclobber; printf '%s\n' "$nonce" > "$lab/control/$phase.request")
for attempt in $(seq 1 450); do
  if [ -f "$lab/control/$phase.ready" ]; then printf 'fixture_phase=%s\n' "$phase"; exit 0; fi
  sleep 0.1
done
printf 'fixture_phase_uncertain=%s\n' "$phase" >&2
exit 2
