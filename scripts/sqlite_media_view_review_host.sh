#!/usr/bin/env bash
# Production media metadata only, both mounts read-only; no socket or host ports.
set -euo pipefail
[ "$(uname -s)" = Linux ] && [ "$#" = 3 ] || { echo 'Usage: bash SCRIPT CACHED_IMAGE_ID SHARED_ROOT NATIVE_ROOT' >&2; exit 2; }
image=$1 shared=$2 native=$3
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
for root in "$shared" "$native"; do
  [[ "$root" = /* && ! "$root" =~ [[:cntrl:],] && -d "$root" ]] || exit 2
  [ "$(cd -P -- "$root" && pwd -P)" = "$root" ] || exit 2
done
checkout=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$checkout"
git -c "safe.directory=$checkout" diff --quiet HEAD -- app scripts || { echo 'Committed review sources required.' >&2; exit 2; }
[ "$(docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || exit 2
volumes=$(docker image inspect --format '{{json .Config.Volumes}}' "$image")
[ "$volumes" = null ] || [ "$volumes" = '{}' ] || exit 2
git -c "safe.directory=$checkout" archive --format=tar HEAD app scripts | \
 docker run --rm -i --pull=never --network none --read-only --user 0:0 --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 32 --memory 512m \
  --tmpfs /fixture:rw,noexec,nosuid,nodev,size=64m \
  --mount "type=bind,src=$shared,dst=/shared,readonly" \
  --mount "type=bind,src=$native,dst=/native,readonly" \
  --workdir /fixture --entrypoint /usr/local/bin/python3 "$image" \
  -I -S -B -c 'import io,os,subprocess,sys,tarfile; tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode="r:").extractall("/fixture/code",filter="data"); os.chdir("/fixture/code"); subprocess.run([sys.executable,"-S","-B","-m","scripts.sqlite_media_view_review"],check=True,timeout=75)'
