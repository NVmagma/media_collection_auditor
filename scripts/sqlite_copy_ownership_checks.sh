#!/usr/bin/env bash
# Fixed disposable suite wrapper; shared runner owns validation and isolation.
set -euo pipefail
[ "$#" = 2 ] || exit 2
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/sqlite_boundary_checks.sh" copy-ownership "$@"
