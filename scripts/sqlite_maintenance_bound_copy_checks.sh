#!/usr/bin/env bash
# Fixed disposable integration suite; never production maintenance controls.
set -euo pipefail
[ "$#" = 2 ] || exit 2
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/sqlite_boundary_checks.sh" maintenance-bound-copy "$@"
