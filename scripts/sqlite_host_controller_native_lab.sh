#!/bin/bash -p
# NEW preparation state only. No production service, setting, mount or boot changes.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077
[ "$(uname -s)" = Linux ] || { echo 'Run on the Linux host.' >&2; exit 1; }
[ "$#" = 2 ] || { echo 'Usage: bash -p SCRIPT EXISTING_RUNTIME_ROOT EXISTING_LAB_BASE' >&2; exit 1; }
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
checkout=$(dirname -- "$source_dir")
runtime=$(realpath -e -- "$1")
base=$(realpath -e -- "$2")
[ -d "$base" ] && [ -d "$runtime/rootfs" ]
[ -f "$runtime/.disposable_controller_runtime" ] && [ ! -L "$runtime/.disposable_controller_runtime" ]
cmp -s -- "$runtime/.disposable_controller_runtime" <(printf 'DISPOSABLE CONTROLLER RUNTIME ONLY\n')
image=${SQLITE_LAB_IMAGE:-python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1}
[[ "$image" =~ ^([A-Za-z0-9._:/-]+@sha256:|sha256:)[0-9a-f]{64}$ ]] || { echo 'Immutable cached lab image required.' >&2; exit 1; }
docker image inspect "$image" >/dev/null
volumes=$(docker image inspect --format '{{json .Config.Volumes}}' "$image")
[[ "$volumes" = null || "$volumes" = '{}' ]] || { echo 'Image-declared volumes refused.' >&2; exit 1; }
lab=$(mktemp -d -- "$base/native-controller.XXXXXX")
printf 'DISPOSABLE HOST CONTROLLER LAUNCHER ONLY\n' > "$lab/.disposable_host_controller_launcher"
printf 'Lab directory: %s\n' "$lab"
# Only fixed Python source files are exposed to this temporary packager. No
# checkout .env, production data, host settings or administrative socket is bound.
files=(app/sqlite_host_controller.py app/sqlite_disposable_maintenance_journal.py
       app/sqlite_lock.py app/sqlite_disposable_dispatch_recovery.py
       app/sqlite_disposable_nfs_config_plan.py app/sqlite_nfs_config_candidate.py
       scripts/sqlite_host_controller_bundle.py)
mounts=()
for name in "${files[@]}"; do
  [ -f "$checkout/$name" ] && [ ! -L "$checkout/$name" ]
  mounts+=(--mount "type=bind,src=$checkout/$name,dst=/source/$name,readonly")
done
docker run --rm --pull=never --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m "${mounts[@]}" \
  --mount "type=bind,src=$lab,dst=/lab" --entrypoint /usr/local/bin/python3 "$image" \
  -I -S -B -c 'import sys,json; sys.path.insert(0,"/source"); from scripts.sqlite_host_controller_bundle import build; print(json.dumps(build("/lab/bundle"),sort_keys=True))'
manifest_digest=$(sha256sum -- "$lab/bundle/bundle.json");manifest_digest=${manifest_digest%% *}
entry_digest=$(sha256sum -- "$lab/bundle/controller.py");entry_digest=${entry_digest%% *}
# These invocations are host processes: no Docker exec/run, chroot, unshare or
# mount command. The existing exported runtime is read, never modified.
bash -p "$source_dir/sqlite_host_controller_native.sh" prepare "$runtime" "$lab/bundle" "$lab/control" "$manifest_digest" "$entry_digest"
before=$(sha256sum -- "$lab/control/.host_controller" "$lab/control/controller.lock" "$lab/control/maintenance-request.json")
bash -p "$source_dir/sqlite_host_controller_native.sh" review "$runtime" "$lab/bundle" "$lab/control" "$manifest_digest" "$entry_digest"
[ "$before" = "$(sha256sum -- "$lab/control/.host_controller" "$lab/control/controller.lock" "$lab/control/maintenance-request.json")" ]
printf 'status=native_host_preparation_lab_complete\nretained_request_unchanged=true\nproduction_activation=disabled\nexternal_actions_authorized=false\nwriter_exclusion_verified=false\n'
printf 'Only new lab files were written; existing runtime and production services/configuration unchanged.\n'
