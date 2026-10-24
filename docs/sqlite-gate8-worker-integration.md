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
that revision still required Tower checkpoint acceptance; the subsequent
correction and passing native results are recorded below. Later documentation-only
commits preserve that implementation tree.

## Native directory-stream failure and correction

At source `af3fd5576549c828ca808ae2189157b501d53648`, Tower's shfs run
(`/mnt/user/sql_test/scheduled-worker.O47sOt`) passed all 14 worker, 16 checkpoint
and 11 HTTP cases. The native run (`/mnt/media/sql_test/scheduled-worker.BrGsWL`)
passed all 14 worker cases and 15 checkpoint cases, but failed
`test_new_title_during_rebuild_stops_without_second_checkpoint`: no exception
was raised for the newly created title. Native checkpoint acceptance remained open at that revision;
that run did not reach its HTTP cases or the success status.

A local reproducer confirmed that `os.scandir(fd)` can interfere with another
iterator because duplicated descriptors share the same open-file-description
position. Each scan now opens `.` relative to the held directory to obtain an
independent directory stream. This preserves descriptor-based path binding while
avoiding shared cursor/iteration state in repeated inventory and content scans.
Worker verification also compares stage directory size/mtime/ctime before and
after collection, blocking observed metadata changes even when the final name
set is unchanged. It does not claim external writer exclusion.

New regression tests cover an active iterator's cursor, a new entry between
passes and stage metadata changes without a name change. The originally failing
checkpoint case is unchanged; it must pass on Tower before accepting this fix.
No moves, overwrite/copy fallback, skipped scenarios or production changes were
introduced. Development-host scheduled tests passed 216 tests and 14 subtests;
46 Linux-only cases passed separately with the 14 worker, 16 checkpoint and
11 HTTP fixtures in an isolated Linux container.

[Test-only CI run 40106982646](https://github.com/NVmagma/media_collection_auditor/actions/runs/40106982646)
passed for correction `7c2a747ff86107cb9baa7dbe440b37f55b7474ae`: 251 scheduled
tests and 18 subtests, 23 atomic regressions, 671 SQLite regressions and 204 isolated
safety tests (separate steps). No image was built/deployed. Tower must still confirm
the correction; rerun the same disposable command above on both views.

The correction was accepted on Tower at source
`170d11e02410fc12d993277a77cae99e5cc96b67`:

- shfs: `/mnt/user/sql_test/scheduled-worker.HTfNME`, 14 worker tests in 0.274
  seconds, 16 checkpoint tests in 5.007 seconds and 11 HTTP tests in 0.237 seconds.
- Native: `/mnt/media/sql_test/scheduled-worker.9FCbp1`, 14 worker tests in 0.065
  seconds, 16 checkpoint tests in 4.901 seconds and 11 HTTP tests in 0.236 seconds.

Both reached `scheduled_worker_acceptance_complete`, including the unchanged
previously failing scenario. The disposable checkpoint/rebuild boundary is now
accepted on both views. Production authorization remained false and activation
remained disabled; no production media/services/configuration changed.

## Routed multi-library move integration

`execute_disposable_routed_batch` now performs actual movie/TV directory moves
using one marked lab database and explicit configured stage roots. Preparation
captures root/title identities and the complete immutable configuration. Changed
configuration, roots, title identity, state/revision, pending clock proposals,
protection decisions or expired plans cannot be adopted as a fresh plan.

The batch retains the cooperating runner lock, applies the one scan-wide action
cap and chains exactly three revisions per successful title: durable intent,
applied checkpoint, then atomic source/destination clocks, optional Arr retry
entry and exact intent clearance. Held source and parent descriptors, current
Linux mount binding, no-overwrite rename and parent directory sync guard each
operation. The applied session must still match its exact snapshot/revision;
there is no fresh-session adoption of an intervening writer. Every candidate
refreshes protection. Configured TV Waiting content is observed again before
intent, blocking new content that would reset its clock.

Movie/series titles with identical folder names route to their own libraries.
Earlier completions survive a later failure; the first failed/uncertain candidate
stops the batch without replay or automatic rollback. Unsupported rename has no
copy/delete or overwrite fallback. Arr entries are queued only; no network
mutation is performed. Existing single-tree disposable APIs keep their markers
and contracts. The production worker still rejects SQLite.

An existing Arr queue entry for a candidate blocks its next move even without a
new queue request; unrelated entries are preserved.

The new native-only disposable package runs 22 routed cases (including four
transition subcases and an actual SIGKILL after rename) and 11 HTTP cases:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  bash scripts/sqlite_scheduled_routed_lab.sh /mnt/media/sql_test
)
```

Use the native lab parent, where Gate 6/7 already verified the required rename
capability. This rename package does not accept shfs as rename-capable; the
separate worker/clock package remains valid for its non-move scope. The new
package mounts only its new `scheduled-routed.*` directory, uses a cached immutable
image, no added capabilities/network/host services, and removes only its new
fixture container. Expected final status: `scheduled_routed_acceptance_complete`,
`acceptance_scope=disposable_routed_moves`, production activation disabled and
authorization false. Production media/configuration/state remain untouched.
Development-host scheduled checks passed 218 tests and 14 subtests; the 68
Linux-only cases passed separately. Linux/Python 3.12.15 execution passed all 22
routed cases, 14 worker cases, 16 checkpoint cases, 19 Gate 7 cases, 27 Gate 6
cases and 11 HTTP cases in one new cached-image container without host mounts
or network.

[Test-only CI run 40116233933](https://github.com/NVmagma/media_collection_auditor/actions/runs/40116233933)
passed for implementation `1af16f6fb3bda89ed4de2921eae92c66a8bcad13`: 275 scheduled
tests and 22 subtests, 23 atomic regressions, 671 SQLite regressions and 226 isolated
safety tests (separate workflow steps). No image was built/deployed. Later
acceptance-document-only commits retain that implementation tree. Routed native
Tower acceptance was received for the routed engine at source
`ce90bae015c41a6e94cfbb34394ed6867813ca54`: lab
`/mnt/media/sql_test/scheduled-routed.KyQkzm`, all 22 routed cases in 12.918 seconds
and 11 HTTP cases in 0.238 seconds. Final status was
`scheduled_routed_acceptance_complete`, scoped to disposable routed moves, with
production activation disabled and authorization false. The routed native
boundary is accepted. No production media/configuration/services changed.

## Daily claim, checkpoint and routed dispatch composition

`run_disposable_routed_slot` now composes the due daily claim, complete multi-library
scan, optional exact clock checkpoint, fresh plan rebuild and routed batch under
one cooperating runner lock. Internal locked helpers preserve the existing public
clock/batch wrappers and their mandatory disposable markers; there is no public
skip-lock or activation flag. One total monotonic deadline covers every phase.

A claim must be synced before any collection. It is never removed on completion,
collection failure, uncertain checkpoint or controller death. Repeating a claimed
slot cannot scan or move again, including after a time change on the same zone/local
date. Early/missed slots do not catch up. A new local date can attempt a fresh run,
but unresolved media intents still block it. Partial claim records are never
automatically replaced. Requests are detached before callbacks, bound to observed
titles and filtered by the one globally capped plan; no service mutation occurs.

The 14-case composed stdlib fixture covers successful all-library ordering,
duplicate/date-change rejection, early/missed slots, collection failure, clock
checkpoint/rebuild before Keep moves, lock retention across scan and per-move
refresh, global cap with detached Arr requests, fresh next-date attempts, partial
claim writes, uncertain committed clocks, a shared deadline, pending-intent blocking
on the next date, and an actual controller SIGKILL after rename with retained claim.
Scheduling dates are injected independently of the past lifecycle fixture clock;
production future-clock rejection is unchanged.

Development-host regression checks passed 220 tests and 14 subtests; 82
Linux-only cases were skipped there and exercised separately in the isolated
Linux package. That package passed 14 slot, 22 routed, 14 worker, 16 checkpoint,
19 reconciliation, 27 rename and 11 HTTP cases.
[Test-only CI run 40125278741](https://github.com/NVmagma/media_collection_auditor/actions/runs/40125278741)
passed for implementation `d762583da72a4df27c910adcfe76dac71613ffe3`: 291 scheduled
tests and 24 subtests, 23 atomic regressions, 671 SQLite regressions and 240
isolated safety tests (separate workflow steps). No image was built or deployed.

Native Tower acceptance of the composed workflow is required:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  bash scripts/sqlite_scheduled_routed_slot_lab.sh /mnt/media/sql_test
)
```

This new package runs 14 daily-slot cases and 11 HTTP cases using only its new
`scheduled-routed-slot.*` lab directory and one new fixture container. It uses the
same cached immutable Python image, no network, added capabilities, packages,
production mounts, service controls or kernel changes. Expected final status is
`scheduled_routed_slot_acceptance_complete`, `acceptance_scope=disposable_daily_slot`,
with production activation disabled and authorization false. It performs actual
fixture renames, so use the native parent with previously accepted rename support.
The read-only/clock shfs package is separate. Composed native acceptance passed
at source `e3a513f60b6b2c96612f917896c96fb9441499a8`, lab
`/mnt/media/sql_test/scheduled-routed-slot.808jzw`: all 14 daily-slot tests in
7.500 seconds and 11 HTTP tests in 0.235 seconds. Final status was
`scheduled_routed_slot_acceptance_complete`, scoped to `disposable_daily_slot`;
production remained disabled/unauthorized and unchanged.

## Effective application settings bridge

`scheduled_worker_from_settings` now maps effective application settings to the
immutable scheduled policy without importing the production worker, opening paths,
initializing clients or retaining credentials. Existing `MEDIA_PATH`, individual
Radarr/Sonarr stage overrides, movie/TV enable switches, wait/holding timers,
TV new-content resets, favorites and the shared action cap are preserved. Arr
application paths remain distinct from filesystem paths. Invalid policy, overlapping
roots and enabled deletion/cross-filesystem/season-pruning options are rejected.

The saved-settings schema now accepts `SQLITE_DAILY_RUN_TIME` (HH:MM) and
`SQLITE_DAILY_RUN_TIMEZONE` (IANA). Fields are labeled preparatory: saving them
neither activates SQLite nor changes JSON interval/manual execution. Blank values
can be saved while JSON is in use; scheduled preparation requires both explicit
values and never infers them from `TZ` or `RUN_INTERVAL_HOURS`. No daily defaults
are imposed on existing users. The runtime backend guard remains unchanged.

Tests cover saved-settings round trips, actual production-library-builder parity,
unsupported policies, detachment and credential exclusion. Linux CI also exercises
a policy built from these settings through an actual claimed movie/TV fixture run
with a shared cap and retained daily claim. This configuration-only bridge needs
no additional Tower run; production root/database/entry-point dispatch remains open.

## Configured GET collection and dispatch composition

`run_configured_disposable_slot` connects the effective-settings policy to a new
bounded GET-only Jellyfin transport per attempt, configured tag names, complete
scan-time collection and repeated per-move protection reads. It retains one request
budget through scans, rebuilds and moves. Movie/TV identities come from that
attempt's inventory; scan-time signals are never reused as move-time protection.
Only marked disposable roots are accepted through the existing slot runner.
Explicit `DRY_RUN=false` is required for this fixture rename entry point; production
`run_once` still rejects SQLite before side effects. No Arr delivery is performed.

Four stdlib Linux fixture tests compose settings, actual private loopback HTTP,
daily claims, SQLite and actual no-overwrite renames: two-library success and
no-repeat collection; a configured protection tag appearing after scan blocks
before intent; unavailable HTTP protection leaves clocks/media unchanged and
retains the daily claim; invalid tags/connection/dry-run policy makes no requests
or claim. Unavailable scan signals are safely skipped by the established planner,
not treated as authorization. Local Linux execution also passed the existing 14
slot, 27 rename and 11 HTTP cases. Development-host regression checks passed 249
tests and 14 subtests, with 87 Linux cases skipped there and separately exercised.

[Test-only CI run 40125775453](https://github.com/NVmagma/media_collection_auditor/actions/runs/40125775453)
passed for implementation `73b5195e4fe7bab175f645bfecf692dbf16a1ad1`: 322 scheduled
tests and 27 subtests, 23 atomic regressions, 671 SQLite regressions and 244
isolated safety tests (separate steps). This includes the actual configured
settings-to-dispatch Linux test. No production image was built or deployed.

Native Tower acceptance of this combined boundary passed at source
`3a07827c63db5105b81acc052e12a5497e02435e`, lab
`/mnt/media/sql_test/scheduled-configured-slot.DzqmQ0`: all 4 configured workflow
tests in 1.497 seconds and 11 HTTP tests in 0.235 seconds. Final status was
`scheduled_configured_slot_acceptance_complete`, scope
`configured_disposable_daily_slot`; production remained disabled and unchanged.
The accepted command is retained here for reference:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  bash scripts/sqlite_scheduled_configured_slot_lab.sh /mnt/media/sql_test
)
```

Expected: 4 configured workflow tests plus 11 HTTP transport tests, final
`scheduled_configured_slot_acceptance_complete`, scope
`configured_disposable_daily_slot`. The new lab has synthetic credentials and
responses, no external network access, no production mounts or service/kernel
changes, and only its new directory is writable. Production remains disabled.

## Separate control/database and media roots

The shared locked worker internals now accept an explicitly bound SQLite database
independently of the configured movie/TV roots. Existing disposable public APIs
still require their exact original marker/root layout. A separate
`run_disposable_worker_layout` entry point tests deployment-shaped control/media
separation only inside a marked disposable lab: its separately marked control
directory holds `state.db`, the persistent cooperating lock and daily claims.
All media roots must be inside the outer lab and disjoint from control. Component
no-follow opens and repeated directory/marker/database identity checks bind both
sides; no missing state is initialized or migrated.

The same private checkpoint/rebuild, complete scan, fresh GET protection and routed
move implementation now serves both layouts. Pending intents stop before collection,
including empty malformed intent values. The total deadline starts before control
lock/claim acquisition and is not reset between phases. The configuration capture
also detaches policy and credentials from one effective-settings snapshot.

Eight Linux fixture tests verify separate-state success without creating an outer
state database, retained daily claim/no replay, pending-state refusal before HTTP,
replaced database refusal, control-lock retention during real HTTP, missing marker,
control/media overlap and outside-control refusal, retained intent after a real
rename with uncertain acknowledgement, and invalid deadline refusal before claim.
The full isolated Linux package additionally passed the 4 configured, 14 slot,
22 routed, 14 inventory, 16 checkpoint, 19 reconciliation, 27 rename and 11 HTTP
cases. A JSON entry-point regression verifies preparatory SQLite schedule values
do not affect the legacy JSON callback, existing state or backend guard.

[Test-only CI run 40126252624](https://github.com/NVmagma/media_collection_auditor/actions/runs/40126252624)
passed for implementation `f68189dc25d202c242ccb5ec08daf675bf00039c`: 333 scheduled
tests and 27 subtests, 23 atomic regressions, 671 SQLite regressions and 252
isolated safety tests (separate workflow steps). No image was built/deployed.

Native Tower acceptance for this separated layout passed at source
`04964d1453b368f6f53506510a6efefccc0e522d`, lab
`/mnt/media/sql_test/scheduled-worker-layout.aJpgAO`: all 8 layout tests in
3.039 seconds and 11 HTTP tests in 0.245 seconds. Final status was
`scheduled_worker_layout_acceptance_complete`, scope
`disposable_separate_control_media`; production remained unchanged.
The accepted command is retained for reference:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  bash scripts/sqlite_scheduled_worker_layout_lab.sh /mnt/media/sql_test
)
```

Expected: 8 layout tests and 11 HTTP tests, final
`scheduled_worker_layout_acceptance_complete`, scope
`disposable_separate_control_media`. Only its new disposable directory/container
are used; no external Jellyfin, production media/database/settings/services,
exports, kernel controls or boot settings are touched. Native rename capability
remains required; there is no copy/delete fallback.

## Candidate daily worker/service connection

The service entry point now selects the SQLite daily-service path only behind an
unconditional release activation gate. No environment value bypasses that gate.
JSON retains its existing interval/manual loop and `run_once` behavior. Selecting
SQLite currently fails before starting a web/worker thread, importing the auditor,
loading worker settings or opening state through this branch. The separate
read-only API service branch retains its existing behavior.

Behind that sealed boundary, `ScheduledWorkerCycle` schedules the next strictly
future daily time on startup/configuration change, never runs early on a manual
wake, skips a slot delayed by 60 seconds or more, and advances before invoking its
worker callback. Exceptions therefore cannot trigger an automatic retry. Clock
rewind recomputes a future wall time, while durable local-date claims independently
reject any already attempted date. The daily service polls settings with bounded
waits; it never bootstraps or migrates a database.

The candidate production worker resolves effective settings, binds an existing
`SQLITE_STATE_FILE` (default `/app/logs/sqlite_worker/state.db`, dedicated
`state.db` filename), retains the shared legacy JSON/migration lock derived from
`STATE_FILE`, then binds the control-directory/database inode and persistent
worker lock. Control/media roots must be disjoint. The same accepted claim,
clock checkpoint/rebuild and routed execution internals perform the due attempt.
Missing/replaced state is never adopted or initialized. The original JSON state
is neither read for migration nor modified during this path. Its output remains
non-authorizing while release activation is disabled. The candidate rename path
requires explicit `DRY_RUN=false`; default dry-run settings cannot select live
execution. Arr delivery, deletion, season pruning and service controls remain absent.

Eight stdlib end-to-end runtime fixture tests explicitly construct marked disposable
paths and synthetic credentials, then call these private candidate internals without
changing the public activation gate. They verify startup/early wakes, actual due
movie/TV renames with unchanged JSON, missed slots/restart, shared JSON lock
contention, uncertain rename followed by next-date pending-intent refusal before
HTTP, clock rewind/repeated-date refusal, database replacement and invalid state
binding. Ten pure cycle tests cover timing/configuration/failure semantics. Public
production/service gate tests verify no callback/settings side effects; a subprocess
runs the real `main.py` with tripwire thread/auditor/history stubs to verify rejection.
The actual read-only API entry-point regression remains passing.

Native Tower acceptance of this final candidate runtime is required:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  bash scripts/sqlite_scheduled_runtime_lab.sh /mnt/media/sql_test
)
```

Expected: 8 candidate runtime tests and 11 HTTP transport tests, final
`scheduled_runtime_acceptance_complete`, scope `candidate_daily_worker_runtime`.
Only newly created fixture files/container/private loopback HTTP are used. Public
production activation remains sealed throughout. No production roots, state,
credentials, service controls, exports, boot settings or kernel controls are used.

## Remaining Gate 8 scope

The worker/service connection is implemented behind the release gate. Native Tower
acceptance of the candidate runtime above is the remaining Gate 8 evidence before
closure. The earlier native layout, configured HTTP/slot, routed moves and clock
boundaries remain accepted; the original JSON interval/manual path is unchanged.

Configured Arr delivery and dashboard/status authority belong to Gate 9. Final
image packaging, persistent-path setup, migration/backup/rollback, release runtime
selection and explicit activation approval remain Gate 10 work. Gate 8 closure
will not authorize deployment, migration or SQLite production execution.
