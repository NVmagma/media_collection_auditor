# Gate 10 — release and rollback acceptance

Gates 1–9 are closed for the approved scheduled-run model. Gate 10 is open.
Production remains the existing JSON worker/image. Permanent deletion, season
pruning, cross-filesystem moves and SQLite activation remain disabled. This
record does not authorize a production update or cutover.

## Fixed exit requirements

1. Verify the complete runtime in a candidate image, including JSON/Homarr
   compatibility, actual entrypoint refusal of unapproved SQLite activation and
   the accepted scheduled worker. Test the final source revision in full CI.
2. Accept an operational backup/migration/restore rehearsal on disposable Tower
   storage, including an advanced SQLite revision, pending-operation refusal,
   restart persistence and refusal to restore stale JSON. Preserve evidence and
   original state; no automatic activation or live service controls.
3. Prepare a concrete production cutover and rollback package: immutable image,
   verified paths/configuration, retained backup, stopped cooperating writer and
   explicit recovery rules. No rollback may overwrite newer tracking with stale
   JSON or replay uncertain media/Arr operations.
4. Obtain explicit activation approval after the package is reviewable. Passing
   fixtures or selecting an environment value is not activation approval.

## Candidate runtime packaging

The tracked uppercase `Dockerfile` ships the JSON runtime through an explicit
module list. It cannot package the full accepted SQLite candidate. The repository
also tracks lowercase `dockerfile`; on case-insensitive macOS these paths collide.
This work leaves both recipes untouched and uses the unambiguous
`docker/sqlite-candidate.Dockerfile` instead.

The candidate copies the complete `app` tree once and supplies both package and
legacy flat import paths. It uses Python 3.12 slim through an explicitly supplied
immutable official base digest, labels the exact Git source revision and retains
the unconditional activation gate. No new environment bypass exists.

`scripts/sqlite_candidate_build.py` accepts only `feature/sqlite`, clean runtime
inputs and a pinned official Python base. It builds from `git archive`, not the
potentially colliding/dirty working tree, creates an untagged image, and never
pushes to a registry. The source's requirements are installed with the version-pinned
`docker/sqlite-candidate-constraints.txt`, including transitive runtime packages.
The candidate uses `STOPSIGNAL SIGINT` so Python handles Docker stop explicitly;
the image lab refuses unclean/forced shutdown rather than hiding it.

`scripts/sqlite_candidate_image_lab.py` accepts an exact cached image ID and
matching revision label. It starts only a new constrained container, with no
host mounts, published ports or external network. The actual default entrypoint
serves its private read-only API (401 without token, 200 with the synthetic key),
while a separate actual SQLite entrypoint attempt must refuse activation and
leave fixture JSON bytes unchanged. Accepted coordinator, Arr and TV fixtures
then import application modules from the image, with only committed fixture
scripts copied into container tmpfs. The new container is stopped and removed;
production containers are never inspected for credentials or controlled.

The branch-scoped `SQLite candidate image acceptance` workflow has contents-read
permissions and no registry publication. It runs for candidate/runtime build-input
changes on `feature/sqlite` and also declares manual dispatch. The push trigger
permits branch-only validation without modifying the default branch. It runs the full disposable suite before
building/testing linux/amd64. Local Docker verifies linux/arm64 separately.
Candidate packaging acceptance is pending. Operational restore/cutover acceptance
and explicit production approval remain open.

## Tower candidate-image check (no host Python required)

The Bash wrappers use Tower's Git/Docker directly. Python runs only in the new
image's private test container. Building may download the pinned official base
and pinned Python packages; it never updates an existing container or image tag.
No real Docker socket is mounted into a container.

After CI passes for the implementation, run:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  candidate_image=$(bash scripts/sqlite_candidate_build.sh)
  bash scripts/sqlite_candidate_image_lab.sh "$candidate_image"
)
```

Expected: entrypoint authentication/gate checks, 10 coordinator, 9 Arr, 10 TV
and 11 HTTP cases, then `candidate_image_acceptance_complete`. There are no
production bind mounts, published host ports, external fixture network, registry
pushes, service controls or state migration. The untagged image remains cached;
only the newly created fixture container and temporary image-ID file are removed.
This is candidate packaging acceptance, not operational restore or activation.

## Candidate packaging evidence

Implementation `9c1ae1d9735b2828fc276c11595be58d378c674d` passed
[workflow run 40152538090](https://github.com/NVmagma/media_collection_auditor/actions/runs/40152538090):
**3,141 tests and 49 subtests** passed in 82.15s before the linux/amd64 image build.
The actual default entrypoint, authentication/gate checks and all 40 packaged
coordinator/Arr/TV/HTTP cases passed, followed by the same image's Tower Bash
wrapper. Candidate image ID on that CI host:
`sha256:e6c4d4d2091a2bbe27437e60cc53c53dc2ca842ad69b1004c3bfdfd5a2e0c90c`.
It was not published to a registry; it is not a production pull reference.

Local linux/arm64 build and the actual Bash build/acceptance wrappers passed at
the same source revision, image ID:
`sha256:5472f503e184225fe81a6ffb502ef49755b6aecdda71398f2d11d6d72cbce41c`.
All 18 build/wrapper guard unit cases passed locally. The earlier first-build
trial at `32e0144` passed API/worker checks but failed clean shutdown because the
PID-1 Python process outlasted Docker's default stop signal; that result is not
accepted evidence. The pinned `STOPSIGNAL SIGINT` recipe repaired this boundary,
and both final architecture checks verified clean shutdown without forced kill.

The Python base and all 13 runtime package versions are pinned in the candidate
recipe/constraints. Runtime modules were loaded from the image, not the fixture
archive. Both tracked legacy Docker recipes, existing containers/tags, JSON
production authority and the unconditional SQLite gate are unchanged.

**Tower candidate packaging acceptance is pending.** Gate 10 remains open for
that result, operational backup/migration/advanced-state restore acceptance,
final production cutover/rollback review and explicit activation approval.

## Tower candidate image acceptance

Source `9b8dfbf5122a8bed4ba4606c847dcbd7f468b2c4` passed on Tower with cached
candidate image `sha256:f03a299e190dbc3660642398904ba5c8fd53413bb93c7c1eb8bfbdd72def8f53`.
The actual entrypoint verified 401/200 authentication, SQLite activation refusal
and unchanged JSON bytes. All 10 coordinator, 9 Arr, 10 TV and 11 HTTP cases
passed, ending with `candidate_image_acceptance_complete`; clean shutdown passed.
No production container, tag, mount, port, service or configuration was changed.
This closes the initial Tower packaging boundary, not Gate 10 as a whole.

## Disposable advanced-state restore boundary

`restore_disposable_json` accepts only a marked lab and single private basenames:
`rollback-candidate-*.json` to a **new** `restored-state-*.json`. It cannot accept
an arbitrary destination path, overwrite original JSON/backup/current output,
activate a backend or control services. The source database, export, original JSON,
backup and request journal stay bound to their held identities and unchanged
bytes; the SQLite session also checks its full snapshot/revision throughout.
Pending operations and stale exports block before creating a restore request.
Both source/output JSON writer locks and the SQLite runner lock are held.

A durable private request precedes staging. Fully written/synced/readback-verified
staging is published with a same-directory atomic no-overwrite hard link; no
copy/replace fallback is used. Only this attempt's staging link is removed after
verified publication. Directory sync, output parity and current-source checks
precede the completion receipt. Every request remains as a no-replay record.
A failed/crashed publication may leave an output and staging link, but no success
is reported and no automatic cleanup, retry or production use is authorized.
Existing completion/request artifacts also block a second attempt.

Sixteen cases verify advanced revision/clock/Arr/unknown-field parity, fresh JSON
load/save/load in separate network-forbidden processes, stale/pending refusal,
occupied and concurrently occupied destinations, escaping names, symlink and
identity substitution refusal, concurrent SQLite changes, partial writes, sync
failure, writer contention and actual SIGKILL immediately after publication.
A standalone rehearsal retains successful and interrupted examples under a new
`restore-evidence.*` directory, including source/backup/database/export, restored
JSON and private request/completion evidence. Synthetic tracking advances are
not claims that production media moved; actual media ordering was accepted in
Gates 6–9. Existing advisory export/inspection functions remain non-authorizing.

The candidate image includes this helper and exercises the restore fixture in
its image acceptance. Tower testing additionally binds only a newly created lab
on each requested filesystem, so backup/publication/restart are tested on the
actual native and shfs paths. No host Python, Docker-socket mount, published
port, production folder, configuration edit or service control is needed.

After exact-implementation CI passes, run on Tower:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  candidate_image=$(bash scripts/sqlite_candidate_build.sh)
  for parent in /mnt/user/sql_test /mnt/media/sql_test; do
    bash scripts/sqlite_restore_lab.sh "$candidate_image" "$parent"
  done
)
```

Expected per filesystem: 16 restore cases plus retained success/interrupted
rehearsals; final `restore_acceptance_complete`, scope
`disposable_advanced_state_restore`. Logs and retained examples remain only in
the newly created host lab. Unsupported publication blocks without fallback.
Tower restore acceptance, concrete live cutover/rollback review and explicit
activation approval remain open. This helper performs no live restore/cutover.
