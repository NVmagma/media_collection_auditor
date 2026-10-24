#!/bin/bash -p
# Preparation-only native entry point. No Docker, mounts, settings or service controls.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077
[ "$(uname -s)" = Linux ] || { echo 'Linux host required.' >&2; exit 1; }
[ "$#" = 6 ] || { echo 'Usage: bash -p SCRIPT prepare|hold|review RUNTIME_ROOT BUNDLE_ROOT CONTROL_ROOT MANIFEST_SHA256 ENTRYPOINT_SHA256' >&2; exit 1; }
mode=$1;runtime=$2;bundle=$3;control=$4;manifest_digest=$5;entry_digest=$6
case "$mode" in prepare|hold|review) ;; *) echo 'Preparation/review mode required.' >&2; exit 1;; esac
for digest in "$manifest_digest" "$entry_digest"; do
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || { echo 'Reviewed SHA-256 values required.' >&2; exit 1; }
done
for path in "$runtime" "$bundle" "$control"; do
  [[ "$path" = /* && ! "$path" =~ [[:space:]\\] && "$(realpath -m -- "$path")" = "$path" ]] || {
    echo 'Canonical unescaped absolute paths required.' >&2; exit 1;
  }
done
[ -d "$runtime/rootfs" ] && [ -d "$bundle" ] && [ -d "$(dirname -- "$control")" ]
marker="$runtime/.disposable_controller_runtime"
[ -f "$marker" ] && [ ! -L "$marker" ]
cmp -s -- "$marker" <(printf 'DISPOSABLE CONTROLLER RUNTIME ONLY\n') || { echo 'Reviewed exported runtime lab required.' >&2; exit 1; }
for name in bundle.json controller.py; do
  [ -f "$bundle/$name" ] && [ ! -L "$bundle/$name" ]
  [ "$(stat -c '%s' -- "$bundle/$name")" -le 1048576 ]
done
actual=$(sha256sum -- "$bundle/bundle.json")
[ "${actual%% *}" = "$manifest_digest" ] || { echo 'Bundle manifest digest mismatch.' >&2; exit 1; }
actual=$(sha256sum -- "$bundle/controller.py")
[ "${actual%% *}" = "$entry_digest" ] || { echo 'Bundle entry point digest mismatch.' >&2; exit 1; }
rootfs=$(realpath -e -- "$runtime/rootfs")
[ "$rootfs" = "$runtime/rootfs" ]
case "$(uname -m)" in
  x86_64) triplet=x86_64-linux-gnu;loader_relative=lib64/ld-linux-x86-64.so.2 ;;
  aarch64) triplet=aarch64-linux-gnu;loader_relative=lib/ld-linux-aarch64.so.1 ;;
  *) echo 'Unreviewed native runtime architecture.' >&2; exit 1;;
esac
loader=$(realpath -e -- "$rootfs/$loader_relative")
interpreter=$(realpath -e -- "$rootfs/usr/local/bin/python3")
for path in "$loader" "$interpreter"; do
  [[ "$path" = "$rootfs/"* && -f "$path" && -x "$path" ]] || { echo 'Contained executable runtime required.' >&2; exit 1; }
done
libraries=
for relative in usr/local/lib "lib/$triplet" "usr/lib/$triplet"; do
  path=$(realpath -e -- "$rootfs/$relative")
  [[ "$path" = "$rootfs/"* && -d "$path" ]] || exit 1
  libraries=${libraries:+$libraries:}$path
done
# Detect fallback for the interpreter's immediate dependencies. Extension-module
# resolution still requires deployment review; this is not a security sandbox.
listing=$(env -i PATH="$PATH" "$loader" --inhibit-cache --library-path "$libraries" --list "$interpreter")
[[ "$listing" != *'not found'* ]] || { echo 'Runtime dependency unavailable.' >&2; exit 1; }
printf '%s\n' "$listing" | awk '/=>/ {print $3; next} $1 ~ /^\// {print $1}' |
while IFS= read -r path; do
  [[ "$path" = "$rootfs/"* ]] || { echo 'Host library fallback refused.' >&2; exit 1; }
done
# Reject Python prefix and observed extension-library fallback before creating
# any control state. Future adapters/modules still require their own review.
env -i PATH="$PATH" LC_ALL=C LANG=C GCONV_PATH="$rootfs/usr/lib/$triplet/gconv" \
  "$loader" --inhibit-cache --library-path "$libraries" "$interpreter" -I -S -B -c '
import ctypes,fcntl,hashlib,json,secrets,sqlite3,struct,sys,uuid
from pathlib import Path
root=Path(sys.argv[1])
if Path(sys.base_prefix).resolve()!=root/"usr/local":
    raise RuntimeError("Python standard-library prefix escaped runtime")
paths=[row.split(maxsplit=5)[5] for row in Path("/proc/self/maps").read_text().splitlines()
       if len(row.split(maxsplit=5))==6 and row.split(maxsplit=5)[5].startswith("/")]
if not paths or any(not path.startswith(str(root)+"/") or path.endswith(" (deleted)") for path in paths):
    raise RuntimeError("Mapped runtime dependency escaped exported runtime")
' "$rootfs"
arguments=("$mode" --root "$control")
if [ "$mode" = hold ]; then arguments=(prepare --root "$control" --hold); fi
# No PYTHONHOME/PYTHONPATH/LD_PRELOAD, arbitrary command, service token or host
# environment is inherited. The fixed entry point verifies every source hash.
exec env -i PATH="$PATH" LC_ALL=C LANG=C GCONV_PATH="$rootfs/usr/lib/$triplet/gconv" "$loader" --inhibit-cache --library-path "$libraries" \
  "$interpreter" -I -S -B "$bundle/controller.py" "${arguments[@]}"
