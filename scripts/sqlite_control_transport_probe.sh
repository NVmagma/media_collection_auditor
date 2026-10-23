#!/bin/bash
# Run in Tower's HOST terminal. Observation only; no socket connections or controls.
set -eu
printf '%s\n' 'read_only=true' 'production_activation=disabled' \
  'production_authorized=false' 'writer_exclusion_verified=false' \
  'restart_inhibition_verified=false'
if [ "$(uname -s)" != Linux ] || [ -f /.dockerenv ]; then
  printf '%s\n' 'status=wrong_execution_context'
  exit 2
fi
if ! command -v ss >/dev/null 2>&1; then
  printf '%s\n' 'status=listener_observation_unavailable'
  exit 2
fi
observe() {
  local kind="$1" listing
  shift
  if ! listing=$(ss "$@" 2>/dev/null); then
    printf '%s\n' "${kind}_status=unavailable"
    return 1
  fi
  printf '%s\n' "$listing" | awk -v kind="$kind" '
    /"(dockerd|containerd|buildkitd)"/ { print kind "_listener=" $0; found=1 }
    END { if (!found) print kind "_status=no_named_listener_observed" }
  '
}
failed=0
observe tcp -H -lntp || failed=1
observe unix -H -lxnp || failed=1
printf '%s\n' 'No sockets were connected; no service/configuration/kernel controls were used.' \
  'Listener names are observations only; missing process visibility is unknown coverage.' \
  'Established streams, alternate namespaces and privileged bypasses remain unverified.'
if [ "$failed" -ne 0 ]; then
  printf '%s\n' 'status=listener_observation_incomplete'
  exit 2
fi
printf '%s\n' 'status=listener_snapshot_complete'
