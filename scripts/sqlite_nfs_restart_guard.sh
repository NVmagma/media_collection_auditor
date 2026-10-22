#!/bin/bash -p
# Deny-only prototype. The lab installs it ONLY in a private mount namespace.
# No sourcing, dispatch, subprocesses, timeout expiry or automatic restoration.
# Blocks stop/status too: the enforcer must use separate reviewed controls.
printf '%s\n' 'NFS service dispatch denied by maintenance guard' >&2
exit 75
