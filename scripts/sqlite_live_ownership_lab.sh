#!/usr/bin/env bash
# Disposable named volume only; no existing media, host paths or socket mounts.
set -euo pipefail
[ "$#" = 1 ] || { echo 'Usage: bash SCRIPT CACHED_IMAGE_ID' >&2; exit 2; }
image=$1
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || exit 2
volumes=$(docker image inspect --format '{{json .Config.Volumes}}' "$image")
[ "$volumes" = null ] || [ "$volumes" = '{}' ] || exit 2
nonce=$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')
[[ "$nonce" =~ ^[0-9a-f]{16}$ ]] || exit 2
volume="auditor-live-ownership-$nonce"
docker volume create --label auditor.fixture-only=true "$volume" >/dev/null
trap 'docker volume rm "$volume" >/dev/null 2>&1 || true' EXIT
common=(--rm --pull=never --network none --read-only --user 0:0 --cap-drop ALL
  --security-opt no-new-privileges --pids-limit 32 --memory 128m
  --mount "type=volume,src=$volume,dst=/lab" --entrypoint python)
# CHOWN is used only to prepare ownership on this new synthetic volume.
docker run "${common[@]}" --cap-add CHOWN "$image" -B -c '
import os
from pathlib import Path
p=Path("/lab")
(p/"control").mkdir(mode=0o700)
(p/"control/state").write_bytes(b"private");os.chmod(p/"control/state",0o600)
(p/"waiting").mkdir();(p/"holding").mkdir();(p/"waiting/title").mkdir()
(p/"waiting/title/media").write_bytes(b"fixture")
for name in ("waiting","holding","waiting/title"):
    os.chmod(p/name,0o755);os.chown(p/name,99,100)
os.chown(p/"waiting/title/media",99,100)
'
docker run "${common[@]}" "$image" -B -c '
from pathlib import Path
from app.sqlite_noreplace_rename import rename_directory_noreplace
assert Path("/lab/control/state").read_bytes()==b"private"
try:rename_directory_noreplace("/lab/waiting/title","/lab/holding/title")
except PermissionError:print("without_dac_override=denied")
else:raise AssertionError("Expected write denial")
'
docker run "${common[@]}" --cap-add DAC_OVERRIDE "$image" -B -c '
from pathlib import Path
from app.sqlite_noreplace_rename import rename_directory_noreplace
p=Path("/lab")
assert all(((p/name).stat().st_uid,(p/name).stat().st_gid)==(99,100) for name in ("waiting","holding","waiting/title","waiting/title/media"))
rename_directory_noreplace(p/"waiting/title",p/"holding/title")
assert (p/"holding/title/media").read_bytes()==b"fixture"
assert all(((p/name).stat().st_uid,(p/name).stat().st_gid)==(99,100) for name in ("holding/title","holding/title/media"))
(p/"control/state").write_bytes(b"updated")
assert (p/"control/state").stat().st_uid==0
print("minimal_dac_atomic_rename=verified private_control_write=verified ownership_unchanged=true fixture_only=true")
'
printf '%s\n' 'status=live_ownership_fixture_complete' 'production_services_changed=false'
