#!/usr/bin/env bash
# Render a NEW private packet only. Docker requires an ordinary bind source;
# procfs descriptor paths are retained for host writes, never used as bind sources.
set -euo pipefail
umask 077
[ "$(uname -s)" = Linux ] || exit 2
[ "$#" = 5 ] || exit 2
image=$1 packet=$2 expected=$3 old_image=$4 control_host=$5
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ && "$old_image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
[[ "$expected" =~ ^[0-9]+:[0-9]+$ ]] || exit 2
[[ "$packet" = /* && ! "$packet" =~ [[:cntrl:],] && ! -L "$packet" && -d "$packet" ]] || exit 2
[ "$(cd -P -- "$packet" && pwd -P)" = "$packet" ] || exit 2
[ "$(stat -Lc '%d:%i' -- "$packet")" = "$expected" ] || exit 1
# The renderer compares the mounted directory identity BEFORE reading private
# inputs or writing outputs. A substituted source therefore cannot receive secrets.
docker run --rm --pull=never --network none --read-only --user "$(id -u):$(id -g)" --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --mount "type=bind,src=$packet,dst=/packet" --entrypoint python "$image" \
  -B -m app.sqlite_preview_cutover --packet-directory /packet --preview-image "$image" \
  --rollback-image "$old_image" --control-host-path "$control_host" \
  --expected-directory-identity "$expected"
[ ! -L "$packet" ] && [ "$(stat -Lc '%d:%i' -- "$packet")" = "$expected" ] || exit 1
