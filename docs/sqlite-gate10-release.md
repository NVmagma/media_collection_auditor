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

Expected: entrypoint authentication/gate checks, 10 coordinator, 9 Arr, 10 TV,
17 restore and 11 HTTP cases, then `candidate_image_acceptance_complete`. There are no
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

Seventeen cases verify advanced revision/clock/Arr/unknown-field parity, fresh JSON
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

Expected per filesystem: 17 restore cases plus retained success/interrupted
rehearsals; final `restore_acceptance_complete`, scope
`disposable_advanced_state_restore`. Logs and retained examples remain only in
the newly created host lab. Unsupported publication blocks without fallback.
Tower restore acceptance, concrete live cutover/rollback review and explicit
activation approval remain open. This helper performs no live restore/cutover.

Restore implementation `848672e52fd5d2a7e4d1f143a1ba9c40c2b48ecf` passed
[CI run 40153655744](https://github.com/NVmagma/media_collection_auditor/actions/runs/40153655744):
**3,160 tests and 53 subtests** passed in 83.74s, followed by the linux/amd64
candidate build, packaged worker/restore tests, actual Bash image wrapper and
actual Bash restore wrapper against new host-backed storage. The final restore
status was `restore_acceptance_complete`. The untagged CI image was
`sha256:416a0a551afdcd0db30d4ce1eda231fa22b88ee6e9bec86f98592fbd3cbb1f2c`;
it was not published or deployed.

Local focused restore/export/restart checks passed 41 tests with 4 subtests.
The standalone 16-case rehearsal retained both completed and interrupted
examples. Local linux/arm64 image acceptance also passed with the packaged
restore helper; its application/fixture bytes match the final implementation
(the final workflow-only change adds the host-backed wrapper check).
Tower restore acceptance on shfs/native remains pending. This evidence does
not authorize a live restore, source-file replacement or backend activation.

## Additional Tower image-only restore report

The operator's subsequent output ended with `candidate_image_acceptance_complete`
and `host_mounts=false`. Its packaged restore suite passed 16 cases in 2.578s,
retained success/interruption evidence inside the private container, and passed
11 HTTP cases in 0.232s. The pasted excerpt did not include source/image identity
or either host lab directory. This is additional image-only evidence; it does
not close the outstanding shfs/native `restore_acceptance_complete` checks.

The [production cutover review draft](sqlite-production-cutover-runbook.md)
records required current bindings, the proposed state-writer/migration sequence
and rollback decision rules. It contains no authorized live commands. Final
production bindings, activation implementation/release verification and explicit
approval remain outstanding alongside the two filesystem acceptance results.


## shfs restore lifetime repair — acceptance pending

Tower source `fd9c8f52e283c6e8fb1e15b490e440cb22c20164`, candidate
`sha256:5a02283168a5afc0b9f39fa7571447c68f63ccf99bf2de3d23a0cd00e76971c3`,
failed the shfs lab `/mnt/user/sql_test/restore.aebcSq`: 14 cases passed and two
success-path cases errored at the strict regular-file/single-link check after
staging unlink. The 16-case run took 8.519s and reported no acceptance. The native
loop iteration did not run because the first failure stopped the command block.
No production files or services were involved.

The staging file descriptor was still open when its staging link was removed.
FUSE can retain an open unlinked inode under a hidden name; this is consistent
with the observed second-link rejection. A descriptor-aware retention model
reproduced the identical exception before repair. The restore now closes its
staging file object before unlinking, while retaining parent/control/input
handles, rechecking staging identity, and preserving the final strict nlink=1,
parity, fsync and current-source checks. Idempotent file-object cleanup prevents
a later ExitStack unwind from closing a reused descriptor number.

The change does not allow extra links, ignore cleanup errors, replace an existing
file or introduce a publication fallback. All 42 focused restore/export/restart
checks and four subtests passed locally after repair. The new standalone suite
contains 17 cases. Rebuild the candidate from the repaired source and rerun both
filesystem labs using the command above; real shfs/native acceptance is still
required. Existing failed labs are not automatically retried, repaired or deleted.

Repair implementation `a4194ad66a883cb05b30266cea2620444c7dccc8` passed
[CI run 40154500531](https://github.com/NVmagma/media_collection_auditor/actions/runs/40154500531):
**3,161 tests and 53 subtests** passed in 94.82s, followed by the candidate image,
actual entrypoint, packaged fixtures, Bash image wrapper and host-backed restore
wrapper (`restore_acceptance_complete`). Local linux/arm64 candidate acceptance
also passed all 17 restore cases, the retained evidence rehearsal and prior
worker/API checks. This verifies the repair on native/container filesystems and
the descriptor-retention model; actual Tower shfs/native confirmation is pending.


## Tower shfs/native restore acceptance

Source `44c1c84cfe075b8c6becdefadd61ea7274ea16cb`, candidate image
`sha256:167c359668cd002b8926d98d6358411bc943909082b2b0a8fe0900c22c322e78`,
passed both actual filesystem labs after the staging-descriptor repair:

- `/mnt/user/sql_test/restore.w6BJGm`: all 17 cases in 10.917s; retained evidence
  `restore-evidence.945eiazi`.
- `/mnt/media/sql_test/restore.wfGIi2`: all 17 cases in 10.389s; retained evidence
  `restore-evidence.s2tfzozy`.

Both ended with `restore_acceptance_complete`, scope
`disposable_advanced_state_restore`. The application/scripts/tests/build inputs
match the passing repair implementation `a4194ad`; `44c1c84` adds documentation.
This accepts the disposable advanced backup/migration/restore/restart boundary
on Tower, including the actual shfs lifetime repair. No live restore or activation
occurred. Final production binding review and an activation-capable release still
require implementation/review/tests and explicit approval.

## Read-only production binding observations

`scripts/sqlite_release_preflight.py` is standalone standard-library code, run by
the existing container's Python through stdin. It imports no auditor/application
modules, calls no services and writes/locks nothing. It reports only whitelisted
prospective saved-config/environment settings, directory identities and a bounded
regular/no-alias source JSON shape/hash/count observation. Tokens, service URLs,
raw title keys and unknown state values never enter its output. Invalid settings
are redacted, and malformed/aliased/changing source files are unavailable rather
than healthy-empty. Full state validation and writer quiescence are explicitly
false; the source hash is a live observation, not an approved migration snapshot.

The tool does not decide an activation schedule or choose a production database
location. Current image, mount mapping, schedule/policy and control location must
be reviewed before the final cutover package can be completed. No changes should
be made to backend selection, images, service state or saved settings for this
observation step.

After CI for the helper passes, run on Tower and share the redacted output:

```bash
cd /mnt/user/sqlite_lab_checkout
git pull --ff-only origin feature/sqlite
docker inspect --format 'image_reference={{.Config.Image}} image_id={{.Image}} running={{.State.Running}} restart={{.HostConfig.RestartPolicy.Name}}{{range .Mounts}}{{printf "\nmount=%s -> %s writable=%t" .Source .Destination .RW}}{{end}}' media_collection_auditor
docker exec -i media_collection_auditor python -B - < scripts/sqlite_release_preflight.py
```

Only the named production container is inspected/read; it is not stopped,
recreated or reconfigured. Do not substitute a full environment/configuration
dump for these commands.

Preflight implementation `6d9256fee62728f34d3f63c7aafafef8ec223c9c` passed
[CI run 40155267584](https://github.com/NVmagma/media_collection_auditor/actions/runs/40155267584):
**3,171 tests and 53 subtests** passed in 102.81s, followed by candidate image,
entrypoint, packaged fixtures, Bash image wrapper and host-backed restore checks.
Both actual image acceptance paths executed the standalone preflight using image
Python 3.12 and reported `read_only_release_preflight_verified`. All ten focused
preflight cases passed locally; combined candidate/preflight guards passed 28.
The next required input is the read-only production binding packet above, not
another restore/image rebuild. No production snapshot or activation is yet bound.

## Scheduled preview release work

The candidate runtime now branches on validated `DRY_RUN` while retaining the
sealed production activation boundary. A due dry-run takes the same JSON/control
locks and durable daily claim, then performs fresh read-only Jellyfin collection
for every enabled library. It returns capped advisory moves without invoking the
rename/Arr dispatcher, creating operation intents, or checkpointing lifecycle
clocks. Discovery changes are explicitly reported and remain uncommitted; when
present, the existing preparation suppresses move proposals until a future live
checkpoint/rebuild. Protection unavailability fails the preview rather than
appearing as a healthy empty list. Process history records preview mode and
separate proposed/completed counts. Changing mode cannot reuse a daily claim.

Ten new disposable cases cover real HTTP collection, discovery non-persistence,
protection failure, pending intent refusal, database replacement, lock contention,
mode-toggle replay refusal, the shared action cap, later-library failure and the
one deadline covering claims/collection. They pass locally, alongside
54 focused tests (five Linux-only checks skipped on macOS). Packaged-image and
host-backed CI now exercise the preview fixture. Actual Tower preview acceptance,
activation-capable release work and final cutover/rollback tooling remain open.

### Preview CI and Tower handoff

Final implementation/workflow revision `a0cb5e8e2d1be8e4cda1acf1858122e8b14dff6f`
passed [CI run 40197836676](https://github.com/NVmagma/media_collection_auditor/actions/runs/40197836676):
**3,181 tests and 53 subtests** in 93.14s, candidate image/entrypoint checks,
packaged preview fixtures through both image wrappers, retained restore acceptance,
and actual host-backed `scheduled_preview_acceptance_complete`.

Earlier runs 40197375282 and 40197536507 passed the suite and packaged fixtures,
but their new host-backed preview step did not execute: BuildKit had not retained
the base as a locally inspectable image, and the default workflow shell hid the
failed left side of a `tee` pipeline. These runs are not host-preview acceptance.
The correction selects the built candidate image and sets explicit Bash for every
run step; the verified logs show `-e -o pipefail`. The final run contains both the
ten-case preview marker and the host-wrapper completion marker.

Run the same disposable wrapper on Tower's actual filesystem paths next. The
build creates an untagged candidate only, without publishing/recreating services;
the labs bind only their own new directories. Host Python is not required:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  candidate_image=$(bash scripts/sqlite_candidate_build.sh)
  for parent in /mnt/user/sql_test /mnt/media/sql_test; do
    SQLITE_LAB_IMAGE="$candidate_image" bash scripts/sqlite_scheduled_preview_lab.sh "$parent"
  done
)
```

Expected on each filesystem: ten preview cases, eleven private HTTP transport
cases, then `scheduled_preview_acceptance_complete`. Share both outputs. Existing
production JSON, media, configuration, services, exports and kernel controls are
unchanged. Gate 10 still requires the activation-capable release and final live
cutover/rollback tooling/review before explicit activation approval.

## Tower preview accepted

Source `5599aade77cd33d6fe0f10733ecf96561222485b` (documentation-only descendant
of tested `a0cb5e8`) passed both actual Tower paths:

- `/mnt/user/sql_test/scheduled-preview.RpJpFr`: ten preview cases in 3.503s,
  eleven transport cases in 0.232s.
- `/mnt/media/sql_test/scheduled-preview.lxxgTJ`: ten preview cases in 3.326s,
  eleven transport cases in 0.239s.

Both reported `scheduled_preview_acceptance_complete`. This closes the actual
shfs/native scheduled preview acceptance boundary; it does not enable SQLite.

## Backup-first release preparation implementation

`app/sqlite_release_preparation.py` now supplies the concrete preparation body and
an explicit offline CLI. It takes a fully validated JSON source, a mandatory exact
SHA-256 and a never-before-used control directory. Linux no-follow parent/source
handles, source identity/content rechecks and the same adjacent writer lock keep
the capture bound while writing. SQLite writes use the held directory through
`/proc/self/fd`, so replacing the visible control name cannot redirect writes into
the replacement tree. The directory is private 0700; backup and database are 0600.

Preparation creates a durable request, a byte-exact original JSON backup and new
`state.db`, then verifies all tracking/unknown/Arr fields and revision zero before
writing its completion receipt. Duplicate/nonfinite JSON, incomplete state,
pending-operation presence, aliases, hardlinks and occupied destinations are
refused. Partial artifacts are retained; neither partial nor completed control
directories can be replayed/adopted. The CLI emits only bounded receipt fields or
a redacted failure category, never title payloads or exception text.

The receipt explicitly says `release_state_prepared_not_activated` and
`writer_quiescence_verified=false`: advisory locking does not stop an old or
noncooperating auditor. All auditor writers must be stopped for an eventual live
preparation. Receipt/file presence does not permit activation or recovery.
This tool changes no backend setting, service, export, media or original JSON.
Its execution against production is still part of the final reviewed cutover and
requires approval; no live command is being requested now.

Nineteen disposable cases cover preservation, no overwrite/replay, stale hash,
malformed inputs, pending/alias/FIFO/lock refusal, source/control replacement,
partial backup, writable-ancestor refusal, receipt corruption, wrong database parity, actual SIGKILL after
DB creation, and actual CLI success/failure redaction. The lab retains synthetic
prepared and interrupted examples for private review. Candidate image fixtures
and a new host-backed CI step exercise the actual image application code. Actual
Tower acceptance of this new preparation boundary is pending.

The control-parent chain must be root/current-user owned and protected against
other-user renames (trusted sticky directories are allowed). Existing permissions
are never changed to pass preparation. This accounts for SQLite potentially
canonicalizing descriptor paths internally; host administrators remain trusted.

The Gate 10 restore/preview/preparation wrappers now select the invoking host UID
and GID and assert that Python actually uses `/lab` as its temp directory. Python
can otherwise silently fall back from an inaccessible TMPDIR to `/tmp`, which
would invalidate a host-backed CI claim. Tower's accepted labs ran as root with
root-owned lab directories; those results are unchanged. CI must prove the
explicit host-backed assertion under its runner UID.

The first preparation CI run at `990c0ea` passed the full suite and packaged
fixtures, then the strict host-backed restore step correctly failed: its selected
unprivileged UID could not extract scripts into the root-owned `/tools` tmpfs.
The correction assigns each private tools/fixture tmpfs to the selected host
UID/GID with mode 0700 (and makes `/tmp` explicitly sticky 1777). This was checked
with an actual UID 1001 container and private tmpfs write/read. The `/lab` assertion
and strict pipeline failure handling remain in place; the failed run is not
host-backed acceptance.

### Preparation CI accepted; Tower acceptance pending

Implementation/wrapper revision `2181422122a69202a11bc9bcdc461aa8bd34e042`
passed [CI run 40200725722](https://github.com/NVmagma/media_collection_auditor/actions/runs/40200725722):
**3,203 tests and 56 subtests** in 93.21s; image/entrypoint acceptance; all nineteen
preparation cases through both packaged-image wrappers; strict actual `/lab`
host-backed restore, preview and preparation acceptance. The preparation wrapper
ended with `release_preparation_acceptance_complete`, retaining synthetic evidence
`preparation-evidence.5x3rp_f5`. Locally, all nineteen preparation cases passed as
root and UID 1001, plus twenty focused shell/packaging guards and the explicit
unprivileged/private-tmpfs permission check.

Next, run only the new preparation acceptance on both actual Tower filesystems.
No host Python, production mounts/state, service controls or backend changes are
used. Building creates an untagged cached candidate, without publication:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  candidate_image=$(bash scripts/sqlite_candidate_build.sh)
  for parent in /mnt/user/sql_test /mnt/media/sql_test; do
    bash scripts/sqlite_release_preparation_lab.sh "$candidate_image" "$parent"
  done
)
```

Expected on each: nineteen cases and `release_preparation_acceptance_complete`.
New synthetic prepared/interrupted evidence directories remain inside each new
lab. Existing files and production services are preserved. This accepts backup/
migration preparation only; latest-state export/recovery integration, the
activation-capable release and final review/approval still remain before Gate 10
can close. Do not invoke the preparation CLI against live state from these lab
instructions or treat its receipt as activation permission.

## Tower preparation accepted

Source `ce41fc74c21da5811df989ee80f4eff8a3c87621`, candidate image
`sha256:5cccd8466506d628d0041a008bacdce6deec95b59f7956c9c86ac00c71948665`,
passed all nineteen preparation cases on both actual Tower paths:

- `/mnt/user/sql_test/release-preparation.N0wty5`: 3.226s, retained synthetic
  evidence `preparation-evidence.635x29nm`.
- `/mnt/media/sql_test/release-preparation.n9s7cW`: 3.553s, retained synthetic
  evidence `preparation-evidence.bwyov0id`.

Both reported `release_preparation_acceptance_complete`. This accepts backup-first
preparation on actual shfs/native storage. Production remains unchanged.

## Prepared-release recovery implementation

`app/sqlite_release_recovery.py` now provides explicit offline `export` and
`inspect` operations for the latest SQLite state. It validates the prepared
control directory, original JSON/backup and durable preparation records, then
holds the shared JSON writer lock and scheduled-worker lock. Current database
identity, input identities/bytes and snapshot revision/content are checked across
the operation. Unresolved intent presence always blocks export or inspection.

Preparation completion receipts now also record `database_identity` (device and
inode); recovery refuses an unbound older receipt or an identical replacement DB.
The previously accepted synthetic receipts are historical evidence, not inputs
automatically adopted by the new tool. New fixtures prepare their own bound roots.

Every export has a new `rollback-candidate-*.json` plus durable request/completion
records. Partial outputs are retained and cannot be overwritten or replayed.
Inspection requires all three records and rejects stale revisions, same-revision
raw state changes, aliases, incomplete/corrupt receipts and candidate replacement.
The payload preserves latest clocks, Arr queues and unknown fields; the original
JSON and database remain untouched. Successful export/inspection is explicitly
advisory: it does not restore files, select authority, start a service, verify
writer quiescence or authorize production activation.

Eighteen new fixture cases include actual CLI redaction, actual SIGKILL after
candidate creation, concurrent checkpoint/control replacement, no overwrite,
pending/lock refusal, stale/alias/corrupt candidates and real fresh-process JSON
load/save/restart parity on a copy of advanced tracking. Synthetic retained
evidence includes an earlier stale candidate and a current advanced candidate.
All eighteen cases pass under an unprivileged Linux UID; root Linux testing also
passed the preceding sixteen-case set. Full image/host-backed CI and actual Tower
recovery acceptance are the next validation boundaries.

### Recovery CI accepted; Tower acceptance pending

Implementation `bf7e6045d375b2c0e43576341cc4ff6b6813ec69` passed
[CI run 40202252083](https://github.com/NVmagma/media_collection_auditor/actions/runs/40202252083):
**3,224 tests and 56 subtests** in 76.21s, candidate image/entrypoint acceptance,
all eighteen recovery cases through both packaged-image wrappers, and strict
host-backed restore, preview, preparation and recovery checks. Host-backed recovery
reported `release_recovery_acceptance_complete` and retained synthetic evidence
`recovery-evidence.jtilx_wk`. Locally, all eighteen final recovery cases passed as
UID 1001, plus twenty-one packaging/wrapper guards; root testing passed the prior
sixteen-case set including real JSON restart parity.

Run the new recovery boundary on Tower's two actual filesystem paths next. It
creates synthetic prepared state and advanced candidates inside new lab folders;
it does not read production tracking, restore files, switch backend or control
services. Host Python is not required:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  candidate_image=$(bash scripts/sqlite_candidate_build.sh)
  for parent in /mnt/user/sql_test /mnt/media/sql_test; do
    bash scripts/sqlite_release_recovery_lab.sh "$candidate_image" "$parent"
  done
)
```

Expected per filesystem: eighteen cases and `release_recovery_acceptance_complete`.
The retained synthetic earlier/current candidates support private inspection.
Successful acceptance covers latest-state export and stale/pending/crash refusal;
the activation-capable release and final concrete authority-switch package/review
still remain before explicit production approval and Gate 10 closure.
