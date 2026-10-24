# Gate 8 scheduled production worker integration

Status: in progress. The first integration boundary is implemented; it does not
select SQLite in the production worker or dispatch media operations. Gates 6–7
remain closed under the approved scheduled model. Host-wide service fences are
not prerequisites for this work.

## Configuration and complete inventory boundary

`configured_scheduled_worker` consumes the existing `build_libraries()` dictionary
shape without importing the production auditor or initializing its clients. It
captures explicit daily time/timezone, movie/TV lifecycle roots, wait/holding
thresholds, favorite policy and one action cap shared across all libraries.
Movie keys remain literal folder names; TV keys retain `TV/`. Identical movie
and series folder names route to different libraries. Arr client objects and
credentials are not retained.

`prepare_scheduled_worker` pins every configured stage root by opening each path
component without following symlinks. Cross-library overlap, root identity aliases,
duplicate title locations and title symlinks block preparation. Non-directory
stage entries also block this initial boundary; they are not interpreted as media.
The bounded inventory covers all four stages and every configured library before
protection collection. All collectors finish before lifecycle decisions. Root and
title identities are checked again before returning any plan. One total deadline
and title limit cover inventory and collection. This detects observed changes;
it does not exclude external writers or grant a later operation permission.

The existing authoritative Jellyfin collector supplies scan-time signals through
`scheduled_inventory_signal_reader`, using a detached configured tag mapping.
Missing/partial coverage produces no candidate for that title. No scan-time
signal may replace the mandatory fresh per-move protection check.

The default preparation reports untracked titles without creating clocks.
Conflicting/missing clocks remain blocked by the existing decision bridge.
An enabled TV clock-reset policy requires explicit discovery preparation;
ordinary planning rejects it instead of silently ignoring the setting. Whole-show
planning does not invoke season pruning, delete files or deliver Arr requests.

## Acceptance

Development-host scheduled regressions passed 160 tests and 14 subtests. The 46
Linux-only Gate 6/7 cases require actual Linux execution, not a passing skip count.
The new stdlib worker fixture adds eight disposable filesystem cases, including
movie/TV routing, the global cap, duplicate locations, symlink rejection,
root replacement, later-library failure, incomplete Jellyfin coverage and
untracked-clock preservation. Additional focused tests cover custom tags,
configuration detachment, inventory limits and the total deadline.

Linux/Python 3.12.15 execution in a new cached-image container passed all eight
worker cases, 19 Gate 7 cases, 27 Gate 6 cases and 11 HTTP cases. No host paths
were mounted and the fixture container was removed.

[Test-only CI run 40104602109](https://github.com/NVmagma/media_collection_auditor/actions/runs/40104602109)
passed for implementation `917f08454489c16a82d39042aa6eaec4837f1578`:
195 scheduled tests and 18 subtests, 23 atomic regressions, 671 existing SQLite
regressions and 182 isolated safety tests. These are separate, potentially
overlapping workflow steps, not a full release-suite count. No image was built
or deployed. Subsequent acceptance-document-only commits retain that implementation.

Run the committed acceptance package on Tower to verify both filesystem views:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  for lab_parent in /mnt/user/sql_test /mnt/media/sql_test; do
    bash scripts/sqlite_scheduled_worker_lab.sh "$lab_parent"
  done
)
```

Each run uses an immutable cached Python image, a new `scheduled-worker.*`
directory and a new fixture container. Only that new directory is bound writable;
there is no network, package installation, image pull, Docker socket mount or
production credential/configuration access. It now runs 14 worker/discovery cases, 16 disposable clock-checkpoint cases and
11 read-only HTTP cases. It does not
claim rename capability or rerun the native-only Gate 6/7 rename suites. Expected final status:
`scheduled_worker_acceptance_complete`. Production activation remains disabled.
Existing media, state, services, exports, boot settings and kernel controls are
unchanged. This accepts the worker preparation boundary, not all of Gate 8.

## Tower result received 2026-10-24

The first run used `/mnt/user/sql_test/scheduled-worker.n0Dd2i`, source
`e6e530edbadc833858482b44aeb0b628d86ce168`. All eight new worker inventory cases
passed in 0.215 seconds. The package then incorrectly attempted the Gate 7 rename
regressions on shfs. The actual no-overwrite rename returned `EINVAL`, classified
as unsupported; the ensuing reconciliation assertions failed because execution
never reached their commit boundaries. The package failed, and the outer loop
stopped before running the native filesystem. This is not a complete acceptance.

The worker-only Tower package now explicitly accepts preparation/read-only
transport, not media rename capability. Removing the unrelated rename suites
from this package changes no move safeguards and skips no inventory/HTTP tests.
Native Gate 6/7 acceptance remains recorded separately; shfs no-overwrite moves
remain blocked. Any eventual production dispatch must check the actual configured
root capability and must not substitute overwrite-prone rename or copy/delete.
The corrected package passed on both views at source
`3af27ac5020b53ac90a7df16dbed578c43069148`:

- shfs: `/mnt/user/sql_test/scheduled-worker.WrUaRq`, eight worker tests in
  0.183 seconds and 11 HTTP tests in 0.237 seconds.
- Native: `/mnt/media/sql_test/scheduled-worker.ufIF1h`, eight worker tests in
  0.036 seconds and 11 HTTP tests in 0.240 seconds.

Both ended in `scheduled_worker_acceptance_complete`, explicitly scoped to
worker preparation and read-only transport, with production authorization false
and activation disabled. The worker preparation boundary is accepted. The swap
warning was nonblocking. No production services/configuration/media were changed.

## Discovery/content milestone

`discover_clocks=True` adds a pure clock proposal to worker preparation. New
titles with complete six-field protection observations start at scan time in
the stage where they were observed. They do not inherit old filesystem age.
Unknown fields, unrelated queue data and missing-title clocks are retained;
stage/clock conflicts block the proposal instead of guessing a reconciliation.

For configured TV Waiting resets, `observe_scheduled_content` opens directories
without following symlinks and observes descendant files/directories, matching
the existing newest-content policy. Global entry/depth/time limits bound each
observation. Incomplete reads, unsupported entries, future timestamps and observed
identity/metadata changes return no timestamp and block preparation. Empty
content does not rewind a clock. This is change detection, not writer exclusion;
a later move still needs current protection/content validation.

The proposal does not write SQLite. If discovery/reset changes any clock, all
moves from the original plan are suppressed. The remaining worker integration
must checkpoint the proposal with exact source revision/snapshot verification,
then rebuild the plan before dispatch. An old plan cannot authorize execution
using proposed but uncommitted clocks. When no clock changes are needed, the
ordinary plan remains available for later guarded verification.

Focused clock/content/worker checks passed 68 tests. Development-host scheduled
regressions passed 197 tests and 14 subtests, with 46 Linux-only cases verified
separately. An isolated Linux/Python 3.12.15 container passed all 14 worker cases,
19 Gate 7 cases, 27 Gate 6 cases and 11 HTTP cases without host mounts/network.
[Test-only CI run 40105556781](https://github.com/NVmagma/media_collection_auditor/actions/runs/40105556781)
passed for implementation `d2976bd8a48f4e2409c48a9ccd6caa4a4cb4937e`: 232 scheduled
tests and 18 subtests, 23 atomic regressions, 671 SQLite regressions and 188
isolated safety tests (separate workflow steps). No image was built/deployed.

The expanded 14-case worker/discovery boundary passed on both Tower views at
source `0963d560dfb8f9bdb2c7e9c8a670a621492999f8`:

- shfs: `/mnt/user/sql_test/scheduled-worker.TD5P4N`, 14 tests in 0.259 seconds,
  plus 11 HTTP tests in 0.233 seconds.
- Native: `/mnt/media/sql_test/scheduled-worker.2VEq8l`, 14 tests in 0.063 seconds,
  plus 11 HTTP tests in 0.241 seconds.

Both ended in `scheduled_worker_acceptance_complete`, with activation disabled
and production authorization false. Discovery/content observation is accepted;
this does not accept the later checkpoint integration below.

## Guarded clock checkpoint and plan rebuild

`prepare_checkpointed_disposable_worker` connects complete preparation to a real
SQLite compare-and-swap checkpoint under the existing cooperating runner lock.
All roots and the database must belong to a marked disposable lab. It accepts
no saved proposal, performs no moves and cannot activate the production backend.

The adapter binds the exact source snapshot/revision, checkpoints at most once,
then recollects every configured library and rebuilds the plan at the verified
new revision. It never lifts an old plan to a new revision or reuses cached
protections. No-change runs perform no checkpoint. One total scan budget covers
both passes. An exception before or after commit stops without retry/rebuild or
dispatch; committed clocks remain committed if later collection fails. Another
clock change during rebuild stops without a second checkpoint.

The 16-case stdlib checkpoint fixture uses real SQLite files and transactions:
SQL abort rollback, after-commit acknowledgement loss, stale revision and raw
same-revision mutation, a CAS competitor inside save, fresh protections during
rebuild, repeated TV content changes, later-library failures, stage-specific
clock mapping, queue/unknown-field preservation, shared deadlines, missing lab
markers and external-root rejection. The expanded Tower command above now runs
these cases too. They write only the newly created disposable database; production
state/media/services remain unchanged. Focused checkpoint checks passed 16 tests;
development-host scheduled regressions passed 213 tests and 14 subtests. The 46
Linux-only cases passed separately in the isolated Linux run, together with the
14 worker, 16 checkpoint and 11 HTTP cases.

[Test-only CI run 40106351229](https://github.com/NVmagma/media_collection_auditor/actions/runs/40106351229)
passed for implementation `0ace0da3e47c169a19632c8c51019c123445dc55`: 248 scheduled
tests and 18 subtests, 23 atomic regressions, 671 SQLite regressions and 204 isolated
safety tests (separate workflow steps). No image was built/deployed. Tower
checkpoint acceptance is pending; later documentation-only commits preserve this
implementation tree.

## Remaining Gate 8 scope

1. Connect real configured roots/database to the guarded intent, descriptor-bound
   no-overwrite rename and exact atomic reconciliation flow. Preserve Gate 6/7
   behavior without removing disposable markers from their test-only APIs.
2. Accept the disposable CAS checkpoint/rebuild adapter on Tower, then connect
   that ordering to the production worker. Repeat content validation before moves;
   the production worker still rejects SQLite and performs no SQLite dispatch.
3. Connect the daily worker/slot ownership and settings path, with one run-wide
   action cap, duplicate-run prevention and no uncertain-operation replay.
4. Verify both production-shaped movie/TV routing and unchanged JSON execution
   through end-to-end disposable acceptance. Keep backend activation blocked
   until the later integration/release gates and explicit approval.

Configured Arr delivery and dashboard authority belong to Gate 9; final image,
backup/rollback and activation approval remain Gate 10 work.
