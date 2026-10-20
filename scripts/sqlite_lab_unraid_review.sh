#!/bin/sh
# Read-only Docker/Unraid lab evidence review. Never authorizes writes.
set -eu
cd /mnt/user/sqlite_lab_checkout
compose_file=docker-compose.sqlite-lab.yaml
container_name="sqlite-lab-review-$$"
cleanup() { docker rm -f "$container_name" >/dev/null 2>&1 || :; }
trap cleanup EXIT HUP INT TERM
docker compose -f "$compose_file" --profile sqlite-lab run -d \
  --name "$container_name" --entrypoint /bin/sh sqlite-lab -c 'sleep 120' >/dev/null
mounts=$(docker inspect "$container_name" --format '{{json .Mounts}}')
probe=$(docker exec "$container_name" python -m scripts.sqlite_lab_mount_probe)
printf '{"mounts":%s,"probe":%s}\n' "$mounts" "$probe" | \
  docker compose -f "$compose_file" --profile sqlite-lab run --rm -T \
    sqlite-lab -c 'import json,sys; from pathlib import Path; from scripts.sqlite_lab_host_inspect import compare_unraid_mount_evidence; x=json.load(sys.stdin); result=compare_unraid_mount_evidence(x["mounts"],x["probe"],Path("/mnt/user/sqlite_lab_test"),Path("/mnt/user/sqlite_lab_checkout")); print(json.dumps(result,indent=2,sort_keys=True)); sys.exit(0 if result["status"]=="review_required" else 1)'
