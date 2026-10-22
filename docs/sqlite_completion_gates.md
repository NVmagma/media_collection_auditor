# SQLite feature completion gates

This is the fixed-scope checklist for `feature/sqlite`. Do not equate a
percentage of tests passing with readiness to run SQLite in production.
A gate is complete only when its acceptance criteria are verified.

| Gate | Acceptance criteria | Current state |
| --- | --- | --- |
| 1. Storage and schema | Validated SQLite snapshot, durable revisioned persistence | Complete: isolated tests |
| 2. JSON migration and parity | Backed-up migration, mismatch detection, unknown fields preserved | Complete: isolated tests |
| 3. Guarded checkpoints | Compare-and-swap, stale-writer rejection, uncertain checkpoint quarantine | Complete: isolated tests |
| 4. Lifecycle decision parity | Representative movie/season clocks and read-only rehearsal | Complete: isolated tests |
| 5. Restart and failure rehearsals | Pending intents persist, crashes fail closed, no automatic replay | Complete: disposable Unraid tests |
| 6. Trusted move verification | Bind identity and paths, independently prove the moved object, reject races and ambiguous outcomes | In progress: native Unraid tests verify live source-retaining Waiting/Holding completion, held paths, fresh protections and failure retention. shfs rejects no-replace publication and retains source/intent. External-writer ownership, atomic source-entry fencing and production crash trust remain open |
| 7. Atomic lifecycle reconciliation | Verified move clock change and intent clearance commit together; failure injection proves all-or-nothing | In progress: Unraid verifies atomic Waiting/Holding destination clocks, stable Arr queue, retained-original ledger and intent clearance, including uncertain commits. Production completion still depends on gate 6 and live integration |
| 8. Production lifecycle integration | Real Waiting/Holding/Keep/Removal moves use guarded ordering; existing JSON path unaffected until cutover | Not wired: capped, revision-chained isolated batches support Waiting/Holding decisions and stop on uncertainty; production audit paths still reject SQLite |
| 9. External integrations | Arr uncertain outcomes, Jellyfin protection, dashboard authoritative reads, TV-season behavior | In progress: 539-title live advisory coverage, bounded fresh protection scans, one-shot Arr uncertainty, and whole-show copy preservation are verified. Production Arr verification, dashboard authority and season-pruning execution remain open |
| 10. Deployment and rollback | Disposable Unraid end-to-end tests, full CI, Docker build, backup/rollback, explicit activation approval | Incomplete: full native Unraid suite passed 1,650 tests and 22 subtests through d67b7da; maintained shfs suite passed 475 tests and 19 subtests. Accepted operational restore, final release CI/image and explicit activation approval remain open |

## Current decision

Five of ten *gates* have been met, but these gates do not represent equal
amounts of work. Do not publish an overall percent complete without a
documented weighting and stable denominator. Earlier 90% and 65–70% estimates
used different scopes and should not be compared or treated as reliable.

Production authority remains JSON. SQLite production activation and permanent
filesystem deletion remain disabled.

## Next engineering task

Extend the disposable witnessed-move contract into a production-reviewed,
trusted verification design **before** permitting production intent clearance. The existing directory fingerprints, unique-location checks,
and persisted-intent binding are advisory. A matching inode or metadata record
is not proof of a completed move, particularly across mounts or after crashes.

The verifier design must explicitly address source/destination identity,
symlink and path substitution, concurrent writers, same-filesystem rename
versus cross-filesystem copy, and what happens when identity cannot be proven.
Uncertain outcomes must remain pending for operator review. Disposable atomic checkpoint/intent-clearance tests with injected failures
exist; production wiring remains blocked until verifier and recovery designs
are reviewed.

## Status reporting rule

For each milestone report: changed files, commit, tests executed and where,
newly completed gate (if any), remaining blockers, and whether production
behavior changed. A new test does not by itself complete a gate.


## Evidence and delivery order — October 20, 2026

The user verified 998 SQLite fixture tests on Unraid for the earlier coverage
increment, followed by 125 focused fixture tests and a successful live read-only
coverage/protection report through `f48c9e9`. That report covered 539 of 539
tracked titles in 13 requests, with no blocked titles or transport failures.
Observed counts were favorite=7, keep=3, keep_all=2, protected=1; counts overlap.
Production activation was disabled and freshness independently unverified.
This is meaningful integration evidence but does not complete gates 6–10.

The remaining implementation should follow this order. Do not treat additional
aggregate report fields as progress on the production move/checkpoint barrier.

1. **Close the move verification design (gates 6–7).** Define the supported
   filesystem/mount model and writer ownership. Start with same-filesystem
   atomic no-replace rename; reject cross-filesystem operations until a separate
   copy/verification contract is implemented. Bind held directory handles,
   intent identity, source/destination roots and SQLite revision. State exactly
   which substitution and concurrent-writer threats are covered. A single audit
   lock does not exclude Arr or manual writers. Crashes that destroy the live
   witness must remain pending for operator review, not auto-clear from inode
   matches or apparent destination presence. Acceptance requires disposable
   Unraid tests of writer contention, path substitution, crashes and uncertain
   commit outcomes. Existing disposable helpers cannot simply be relabeled as
   production-safe.
2. **Implement the isolated SQLite lifecycle runner (gate 8).** Use the reviewed
   contract for intent-before-move and clock/intent checkpoint-after-verification.
   Preserve action caps and tracking history. Every production move touchpoint
   must use this ordering; startup must stop on unresolved intents. First prove
   the runner with disposable media, while `run_once()` retains its JSON gate.
3. **Finish external behavior (gate 9).** Bind fresh Jellyfin protection to each
   planned action, including full-show/season retention. Persist Arr retry and
   unknown-outcome handling without blind replay. Verify dashboard reads against
   the same authoritative revision. The current live probe is diagnostic only.
4. **Rehearse cutover and rollback (gate 10).** Stop writers, preserve verified
   JSON backups, migrate and prove parity on disposable Unraid storage; prove
   persistence, restart and rollback after SQLite has advanced. Do not restore
   stale JSON over newer tracking history. Run the full suite on the final
   revision; the earlier 998-pass result is not evidence for later revisions.
5. **Release verification and explicit activation.** Only when implementation
   and rehearsals are complete, obtain approval for manual CI/Docker verification
   and review the built image before proposing a container update. SQLite
   activation needs explicit approval. Permanent deletion remains separately
   disabled.

No overall completion percentage or calendar ETA is justified by the present
evidence. Storage is implemented; end-to-end production orchestration is not.
The next major milestone is the move contract and isolated runner, rather than
more coverage-summary extensions.

A preflight defect discovered during this review allowed nested stage roots to
pass the overlap check. The guard now treats identical and ancestor/descendant
roots as overlapping, while accepting similarly named siblings. This is a
read-only diagnostic check, not trusted move-time path verification: it does not
prevent later mount/path changes or grant intent-clearance authority.

### Isolated single-writer runner increment

The full 1,025-test Unraid baseline through `6f348bc` passed. The next increment
introduces a lock around the entire existing disposable move/checkpoint flow,
with startup pending-intent precedence and stale-revision rejection. See
[the isolated runner contract](sqlite-isolated-runner-contract.md) for its threat
model, ordering and remaining production blockers. This advances cooperating
writer isolation but does not complete a gate or enable production execution.


The isolated-lock increment subsequently passed all 1,036 SQLite tests on
Unraid. The following descriptor-relative rename increment advances parent-path
binding in that runner, with adversarial substitution tests; source-entry races
and external-writer ownership remain unresolved. No production gate is newly
complete and no production behavior changes.

The descriptor-relative runner passed all 1,054 SQLite tests on Unraid through
`a2d58ba`. The following increment binds root/marker/database/lock observations
across startup and execution boundaries and stops on substitution. Uncooperative
writer isolation and trusted crash clearance remain open; no new gate is claimed.


All 1,062 SQLite tests passed on Unraid through `c3ee114`. The next increment
moves observation-time validation ahead of intent/rename and binds lifecycle
clock reconciliation to the durable request. Production gates remain unchanged.


All 1,071 SQLite tests passed on Unraid through `ddd71c4`. The following increment
supports explicitly named disposable title folders bound to standard movie/show
tracking keys. It removes the single-title fixture limitation without connecting
production execution, season pruning, or activation. Gates 6–10 remain open.

All 1,086 SQLite tests passed on Unraid through `7509b86`. The following increment
adds a named plan-bound isolated entry point that shares the strict candidate
validator and revalidates decisions under the runner's lock before intent.
It still uses caller-provided signals and does not complete production integration.


All 1,101 SQLite tests passed on Unraid through `57fd06b`. The following increment
collects and refreshes Jellyfin signals inside the isolated runner's operation
window before intent creation. It connects existing collector and planner code
in disposable execution but does not establish independent production freshness
or external-writer exclusion. No production gate is newly complete.

All 1,115 SQLite tests passed on Unraid through `58b3b8b`. The following increment
adds a one-shot disposable Arr delivery boundary with durable intent and
persistent unknown/acknowledged-but-unverified outcomes. Automatic retry and
clearance are refused. Atomic queue creation after a move and independently
verified remote identity/outcome are still open; gate 9 remains in progress.


All 1,130 SQLite tests passed on Unraid through `df44671`. The following increment
atomically enqueues a bound Arr notification with the verified disposable move's
clock update and intent clearance. Stable queued IDs are checked before delivery.
Remote identity verification and production integration remain open; no new gate
is marked complete.


## Gate assessment after the 1,140-test Unraid result

The user reported **1,140 passed, one non-failing Requests warning** on Unraid
through `ac9ae6d`. This verifies the atomic move-to-Arr handoff increment. The
summary table above has been updated to reflect the actual implemented evidence,
not just the earlier prototypes. No production gate is newly complete: **gates
1–5 complete, gates 6–7 and 9 in progress, gate 8 not wired, gate 10 incomplete**.

The recent work is substantive: an isolated named-title runner now combines
process locking, held parent directories, bound lifecycle plans/clocks, bounded
Jellyfin refresh and atomic notification handoff. What is missing is acceptance
of its production trust model and full production integration, rather than the
SQLite transaction engine itself. An increasing fixture-test count does not
resolve those missing acceptance criteria.

Priority is still closing gate 6's operational writer/mount ownership and
recovery contract before production clearance. After that, gate 7 can be
assessed against the accepted verifier, and the existing isolated flow can be
wired through every production lifecycle touchpoint for gate 8. Remote Arr
verification, dashboard consistency and season retention must then complete
gate 9. Final CI/Docker verification is intentionally deferred until a release
candidate, consistent with the request to avoid repeated expensive builds.

This assessment/documentation update changes no executable code and requires no
new Unraid regression run. Production remains JSON-only; no SQLite activation,
container update, automatic uncertain-operation replay or deletion is authorized.

The next gate 6 increment checks Linux mount IDs and namespace identity for held
rename descriptors before intent and across operation boundaries. The supported
single-mount model and unresolved ownership/recovery requirements are now
collected in [the blocked production move trust contract](sqlite-production-move-trust-contract.md).
No new gate is marked complete; production still rejects SQLite.

All 1,153 SQLite tests passed on Unraid through `641144b`. Next gate 6 work moves
from fixture validation to read-only deployment mount/writer discovery. The
inventory is evidence for review, not proof of ownership or activation approval.


## Persistent-storage blocker discovered

The full suite on a fresh dedicated `/mnt/user/sql_test` lab directory produced
**1,125 passed and 34 failed** (one Requests warning) through `f7c3cde`. All 34
failures reach the required no-replace rename and receive EINVAL, or are expected
later-crash assertions blocked by that same syscall rejection. This differs from
the passing `/tmp` suite. No SQLite storage/transaction failure was reported in
that run; this does not establish long-term durability or production readiness.

The required flag is unsupported on the tested access path. Its filesystem type
and native backing paths still need read-only inspection; do not infer a specific
Unraid/FUSE cause without that evidence. Same mount ID/device does not prove
rename-flag capability. Gate 6 has a concrete deployment blocker, not a reason to
fall back to overwriting rename, copy/delete, or skip the failing tests. Preserve
the failed fixture directory and pending intents. No production mount changes
or activation are authorized by these test results.

The full suite passed on native Btrfs lab storage: **1,159 tests** through
`8cae0f5`. The same access model failed the required rename on fuse.shfs. The historical next increment blocked the observed filesystem label before intent.
That label blacklist is now superseded by the public-release portability
requirement: keep filesystem type diagnostic and select safe strategies by
capability, retaining no-overwrite and fail-closed requirements. Gate 6 remains open:
production currently uses the shfs path and still has overlapping external
writers; a native lab pass does not authorize mount changes.


## Public-release portability and API scope

The user confirmed 81 focused native Btrfs tests passed and clarified that users
must not be forced onto this deployment's filesystem layout. The filesystem-name
blacklist is removed; the required atomic no-overwrite rename remains one optional
fast path, with no unsafe fallback. A separate source-retaining verified-copy
staging component starts the portable backend work. It is not a completed move
backend or a newly completed gate. Gate 6 must assess strategy-specific capability,
writer ownership and recovery rather than mandate native Btrfs.

[The product roadmap](product-roadmap.md) also records the requested authenticated
read-only integration API for Homarr, Homepage and other clients. It must use the
active authoritative snapshot and remain independent of SQLite activation. API
implementation is planned separately; no live routes or configuration changed.


Portable staging now passes 11 tests on both shfs and native Btrfs through
`c771de8`. The following increment adds durable copy-stage intents and redacted
blocked recovery status; no source cleanup, promotion or lifecycle commit is
authorized. Portability is progressing without a filesystem-name requirement;
no new production gate is marked complete.

Portable-copy follow-up: Unraid durable-copy tests passed on both shfs and native
Btrfs (20 each through `8c80c74`). Added non-authorizing disposable restart content
inspection; pending intents remain pending even when both content manifests
match. Writer exclusion, production recovery and activation gates remain open.

Unraid confirmed the disposable restart-inspection suite through `b3b329d`
(28 passed on each filesystem). Follow-up malformed-intent and concurrent-change
checks remain advisory and do not complete production recovery/writer exclusion.

Unraid confirmed 39 portable-copy/inspection tests per filesystem through
`b51f2f2`. Portable staging now has a disposable plan-bound entry point with
revision and advisory decision revalidation before intent. This connects planner
parity to copying but does not provide trusted freshness, promotion, source
cleanup or production lifecycle reconciliation; no gate is newly complete.

Plan-bound staging through `ca7b0e7` passed 45 tests per filesystem on Unraid.
Its durable intent now retains the proposed transition and plan revision/time,
validated on inspection without granting recovery authority. Gates unchanged.

Durable transition binding through `56810b7` passed 52 tests on each Unraid
filesystem. Copy staging now rechecks held source content/path and the SQLite
snapshot after advisory review, before intent. This detects observed changes;
it does not establish external-writer exclusion or complete gate 6.

Source boundary revalidation through `93ecbb0` passed 56 tests per filesystem
on Unraid. Portable staging now shares the existing two-scan collector/planner
flow, rejects changed/incomplete protections and checks freshness budget again
at intent after hashing. This is isolated synthetic-transport integration, not
production freshness, promotion or recovery authority. No gate is completed.

Collected-copy integration through `e4e0942` passed 65 tests per filesystem on
Unraid. Whole-show portable staging now has explicit TV-key, nested-season and
refreshed protection regression coverage. This does not implement season pruning,
production TV execution or complete gate 9; gate states remain unchanged.

## Advanced-state rollback candidate milestone

Unraid confirmed whole-show portable copy coverage through `bf57739`: 72 tests
passed on each filesystem. Stop requesting one server run per small follow-up;
use local checks and request consolidated Unraid validation at meaningful
integration boundaries.

A new [disposable advanced-state rollback workflow](sqlite-disposable-advanced-rollback.md)
exports current SQLite history into a fresh private JSON candidate, verifies
parity, rejects unresolved operations and detects later divergence. Tests also
re-import the candidate into a separate offline database and preserve queued Arr
work and unknown fields. This addresses the stale-backup data-loss scenario in
an isolated workflow. It does not authorize restoration, prove production JSON
loader compatibility, establish writer exclusion or complete gate 10. Production
remains JSON-authoritative; no restore, activation, media move or deletion occurs.
Server validation and final release/rollback verification remain outstanding.

### Actual JSON save/restart compatibility

Advanced-state rollback candidates now have process-isolated regressions against
the real JSON load/save functions, followed by a fresh-process reload. Fixtures
cover all lifecycle clocks, movie/TV keys, queued Radarr/Sonarr metadata and
unknown Unicode/nested fields. Tests copy only disposable candidate data and
forbid network requests. This advances gate 10's compatibility evidence, but
actual production restore, stopped-writer cutover, server durability, final
release verification and activation approval remain unverified. No gate is
newly complete and no production implementation changes.

### Cooperating cutover lock hardening

The shared JSON/migration lock now refuses symlinks, hardlinks and nonregular
files and checks held-inode binding, including before nested audit saves.
Separate-process regressions verify actual JSON saves are blocked by migration
and actual migration is blocked by audit, then succeed after lock release.
Production JSON writes gain stricter lock-file validation; backend selection
and media behavior are unchanged. This improves gate 10's cooperating-writer
barrier but does not exclude noncooperating writers, authorize cutover/rollback,
or complete any gate. Consolidated Unraid validation is still pending.

### Consolidated synthetic cutover/restart milestone

A new exclusive-directory rehearsal connects original JSON backup, actual
migration, two advanced SQLite checkpoints, stale candidate rejection, fresh
export and actual JSON load/save/fresh-process restart in one retained fixture.
It takes no production data/configuration, performs no media actions, and never
restores the original JSON. Failed artifacts remain and reports deny activation.
Consolidated Unraid validation is now appropriate for rollback, shared-lock
hardening and portable-copy integration together. Gates remain unchanged until
server/operational/release acceptance criteria are met.

## Consolidated Unraid evidence through `6bad439`

The user confirmed 185 tests and 11 subtests passed on shfs and again on native
Btrfs. This covers advanced-state rollback, actual JSON restart compatibility,
shared-lock hardening/process contention, migration and portable-copy regressions.
The Requests warning was non-failing. This is targeted integration evidence, not
a final full-suite/release run or permission to activate/restore production.

Next gate 9 work binds pending isolated Arr delivery to two fresh GET-only
readbacks, stable queue identity, exact destination folder/root/monitoring and
an unchanged SQLite/local binding. Reports remain non-authorizing; no retry,
queue removal or intent clearance is implemented. See
[the isolated Arr readback contract](sqlite-isolated-arr-readback.md). Synthetic
HTTP regressions do not assert a live Arr test occurred. No gate is completed.

## Consolidated Unraid evidence through `29c6d07`

The user confirmed 267 tests and 11 subtests passed on shfs and again on native
Btrfs, including the GET-only Arr readback milestone. Service responses in these
regressions are synthetic; no live Arr readback or production action is implied.
The Requests warning was non-failing. No gate is newly complete.

### Dashboard snapshot consistency increment

The live JSON dashboard now uses an explicit validated snapshot boundary and
shows malformed/duplicate tracking JSON as an error. Detached consumer copies
and an explicitly invoked revision-bound experimental SQLite reader support
[dashboard parity rehearsals](sqlite-dashboard-snapshot-contract.md) against the
real inventory/health functions. Concurrent changes and pending operations fail
closed. Live backend selection remains JSON; stricter damaged-state validation
is the production-visible change. Gate 9 remains in progress; server validation
for this increment is pending.

## Consolidated Unraid evidence through `ef76a45`

Both filesystem access paths passed 298 tests and 11 subtests, including the
validated dashboard snapshot boundary and real inventory/health parity checks.
The non-failing Requests warning persists. These are targeted regressions, not
full release verification or permission to switch production storage.

A wider review found missing Docker COPY dependencies for the new dashboard
snapshot reader. The recipe now includes its three required modules; isolated
runtime-context smoke tests run outside repository imports without building an
image. The full local suite passed 1,404 tests and 22 subtests, with 30 skips and
18 failures caused by the existing Linux-only rename guard on macOS. A full
Unraid run on a rename-capable disposable lab is now required, using the runner's
explicit `--full-suite` mode. No guard has been removed or weakened to pass.
See [runtime packaging evidence](sqlite-runtime-packaging-validation.md).
Gate states and production backend selection remain unchanged.

## Full Unraid baseline through `ac5d4a7`

The user confirmed 1,452 tests and 22 subtests passed in the full native Unraid
run. The Linux rename tests execute successfully there; the earlier macOS-only
failures are not claimed as local passes. This establishes a full regression
baseline, not accepted production ownership, activation or final image release.

Gate 6 follow-up pins root/source-parent descriptors throughout portable staging
and prevents source-parent/root substitution from producing a verified copy
checkpoint or redirecting staging writes. Prepared intents and source artifacts
remain retained on failure. Tests cover parent/title aliases, parent replacement,
root substitution and descriptor cleanup. No new gate is complete; external
writer ownership, portable promotion/retirement and production wiring remain open.

## Copy parent follow-up accepted as regression evidence

Through `4421fce`, 77 focused portable-copy tests passed on shfs and on native
Btrfs. The Requests warning remains non-failing. Root/source-parent pinning is
verified in fixtures; it does not provide exclusive external-writer ownership.

The [production acceptance plan](sqlite-production-acceptance-plan.md) now states
the remaining implementation work explicitly. The read-only cutover assessment
also reports missing verifier, writer control, portable completion, lifecycle
wiring, restart-clearance and release-image verification, even when snapshots
match and caller integration flags are true. Any pending marker blocks, including
empty/malformed values; non-boolean integration claims remain unverified.
This corrects misleading readiness reporting without enabling production or
completing another gate. No new filesystem/server action requires validation
for this report-only increment; continue implementation before the next
consolidated Unraid milestone.

### First lab publication phase

Verified plan-bound lab copies can now be published to the planned Holding/Keep
path only using actual atomic no-replace rename, with a durable publication
marker beforehand and held-descriptor/content verification afterward. Every
outcome preserves source, original lifecycle clocks and a pending intent. There
is no cleanup, Arr notification, repeat attempt or production caller. Unsupported
publication remains blocked; no filesystem label selects a weaker fallback.
Source retirement, a safe alternative for unsupported publication capabilities,
writer control and production orchestration remain unfinished. Gate states do
not change. Linux publication/crash tests require server validation; report-only
cutover guard checks and the new phases are consolidated in the maintained runner.

## Publication Unraid evidence through `db492e9`

The user confirmed 320 tests plus 11 subtests passed on shfs and 324 plus 11
subtests on native storage. The four native-only publication/crash/race cases
executed successfully. Unsupported-capability retention ran on shfs; it is not
claimed as successful shfs publication. The warning remained non-failing.

The next [copy completion rehearsal](sqlite-disposable-copy-completion.md) keeps
both live witnesses through publication and private source quarantine, then
commits destination clock, optional Arr queue, retained-source record and intent
clearance atomically. Original bytes remain retained and no production caller
exists. Interrupted runs cannot resume from matching persisted metadata alone.
Actual Linux completion/uncertain-commit/full-show cases await server tests.
Production writer ownership, unsupported publication alternatives, long-copy
freshness, recovery, live wiring and final activation remain unresolved; no gate
is newly complete. The cutover guard's portable-completion blocker explicitly
refers to production, not this isolated rehearsal.


## Completion Unraid evidence through `61a6a51`

The user confirmed 324 tests plus 11 subtests passed on shfs and 338 plus 11
subtests on native storage. Native completion, crash, full-show and uncertain
transaction cases passed. The shfs result exercises retained blocked outcomes
where the required atomic publication syscall is unsupported.

The next increment permits a long staging transfer followed by two unchanged,
bounded observations in the same live completion invocation. Deadline checks
also guard both renames after durable checkpoints. Pre-intent and later hashing
remain bounded; asynchronous completion, production writer exclusion, restart
clearance and activation remain unfinished. No gate changes status.


## Transfer-window Unraid evidence through `6cfc88a`

The user confirmed 331 tests and 11 subtests passed on shfs, and 346 tests and
11 subtests on native storage. Long staging transfer renewal and deadline guards
passed; hashing remained bounded in that revision. The Requests warning remained
non-failing. No gate changed status or production behavior.

The next live-only increment places full content hashing before paired fresh
collection at each completion boundary, then compares exact whole-tree metadata
with those hash observations. It retains digest verification, revision checks,
held paths, bounded collection/action deadlines and pending-on-uncertainty.
Source/copy changes during collection, late protection changes, revision races,
retained-source substitution and long simulated hashing are tested with
synthetic fixtures. Actual Linux late-phase cases need Unraid validation.
External-writer ownership, trusted production verification, unsupported
publication alternatives, restart clearance and activation remain unfinished.

## Hash-window Unraid evidence through `7615553`

The user confirmed 345 tests plus 11 subtests passed on shfs and 371 tests plus
11 subtests on native storage. Slow hash windows, intervening-change guards and
native late-phase failure cases passed. The warning remained non-failing.
Production activation/deletion stayed disabled and no gate changed status.

The next [bounded batch rehearsal](sqlite-isolated-copy-batch.md) adds an explicit
attempt cap, whole-selection preflight, one held cooperating-runner lock,
revision chaining and stop-on-first-uncertainty semantics. Earlier committed
operations remain intact and later titles are never attempted after failure.
This advances isolated orchestration for gate 8, not production wiring. Native
multi-title, mixed Holding/Keep, Arr queue, checkpoint-uncertainty and unexpected
writer cases require Unraid validation. Gate states remain unchanged.


## Capped-batch Unraid evidence through `3a6a50c`

The user confirmed 367 tests plus 11 subtests passed on shfs and 402 tests plus
11 subtests on native storage. Batch caps, mixed movie/show completions, typed
Arr queues, lock contention, revision chaining and uncertain checkpoints passed.
The Requests warning remained non-failing. No production behavior changed.

The next increment extends source-retaining copy completion to the existing
Holding-to-Keep and Holding-to-Removal decisions. A shared stage/clock mapping
binds inspection, paths, held descriptors and final atomic reconciliation.
Removal remains a non-deleting lifecycle move with original bytes retained.
Waiting/Holding may be mixed within the existing attempt cap; Keep/Removal
sources, season pruning and deletion stay excluded. Native Holding crashes,
uncertain commits and whole-show cases require Unraid validation. Gates 6–10
remain open; external writer control and production orchestration are not solved
by these isolated transitions.


## Holding-transition Unraid evidence through `f37cb39`

The user confirmed 380 tests plus 11 subtests passed on shfs and 432 tests plus
11 subtests on native storage. Holding rescue, non-deleting Removal copies,
whole-show season preservation, source-clock binding, mixed-stage batches,
late protection failures and uncertain final checkpoints passed. The Requests
warning remained non-failing. No production behavior changed or gate closed.

The top-level gate assessment now reflects these verified isolated behaviors.
The previous full-suite Unraid baseline is still 1,452 tests and 22 subtests at
`ac5d4a7`; it does not validate later changes. Refresh the complete native suite
at the current revision before extending production orchestration. This requires
only disposable fixture storage, no production mounts, image build, CI dispatch,
container update or backend activation. Retain the full-suite lab for review.


Full local macOS regression through `f37cb39`: 1,483 passed, 82 skipped,
18 failed, and 22 subtests passed. All 18 failures stopped at the explicit
`Atomic no-replace rename requires Linux` guard, including crash tests that
could not reach their injected boundary. The skips also require Linux. This is
not a full-suite pass; no guard or test was weakened to hide platform limits.
The native Unraid run must exercise all 1,583 collected cases at this revision.


## Full-suite Unraid baseline through `fff83c0`

The user confirmed **1,583 passed and 22 subtests passed** on native disposable
storage, with the existing single non-failing Requests warning. This supersedes
the earlier 1,452-test full-suite baseline for source through `f37cb39` (the next
commit changed documentation only). It validates the combined isolated flows;
it does not establish production writer exclusion or close gates 6–10.

The next concrete writer-control fix makes manual JSON rescue share the audit/
migration process lock. Its previous in-memory guard did not exclude a rescue
in another process during migration or audit. The rescue now checks the JSON
backend before and after auditor import, holds the shared lock around its full
operation, and verifies binding before move/save/notification. The runtime
recipe also includes the backend gate dependency. See
[writer coordination](sqlite-writer-coordination.md) for scope and remaining
external-writer requirements. No Arr/share/host writer exclusion is claimed;
production SQLite activation and deletion remain disabled.


Local validation for the cooperating-writer increment: the focused command
passed 113 tests and 19 subtests, including real child-process contention and
configuration-drift guards. The broader maintained regression set passed 422
tests and 19 subtests before the final configuration-binding checks were added;
the focused set was rerun after those checks. Runtime imports were verified from
COPY inputs only; no Docker build or production container update was performed.
Use `--writer-coordination-only` on both persistent lab paths for the next server
validation; another complete native-suite repeat is not required for this
focused acceptance step. External-writer exclusion remains unverified.


## Cooperating-writer Unraid evidence through `a15830b`

The user confirmed 113 tests and 19 subtests passed on both shfs and native
storage, with the existing single non-failing Requests warning. Cross-process
manual rescue/audit/migration exclusion, backend/configuration guards and runtime
packaging checks are server-tested. This closes that application coordination
gap, not external writer exclusion or gate 6.

The user confirmed shares/host jobs can write media and accepted an explicit
maintenance window as the initial ownership design requirement. No service or
configuration change was authorized. The
[maintenance ownership plan](sqlite-maintenance-ownership-plan.md) requires
independently enforced write denial, restart control, live protection reads and
safe recovery before any production move. Fresh deployment metadata and the
host job/share inventory are the next inputs; a window preference is not an
executable permit. Gate states and production activation/deletion stay unchanged.

## External-writer inventory review after `ce41179`

The user supplied the requested selected-field deployment inventory. It confirms
active broad writable media routes, nested Jellyfin routes, stopped potential
writers, automatic restart policies, a privileged potential writer and Docker
socket administrative routes. Share configuration observations do not establish
effective write denial. The host job/manual-transfer inventory remains pending;
no absence of host writers is inferred.

The maintenance ownership plan now maps these roles to required controls and
explicitly keeps Jellyfin protection reads available. Arr outcomes must be
resolved before restoring its media write access. Passing checkout tests do
not identify the running auditor image or make its cooperation authoritative.
No service/configuration changes or production execution were authorized or
performed. No gate changes status; the next required input is the remaining
host/share writer map, followed by a real enforcement backend and disposable
controller-failure acceptance tests.

### Operator clarification: manual Mac copies use NFS

The operator identifies normal writers as Arr and occasional manual Mac copies
over NFS. No scheduled host job was identified; exhaustive absence is not
assumed. The next targeted read-only input is `exportfs -v`, retaining export
paths, client-selector distinctions and options so overlapping exports can be
reviewed. This does not establish ownership or authorize export/service changes.
Gate 6 remains open pending an enforceable adapter and disposable tests of
existing handles, reconnects and failure recovery. Other production blockers
and deletion safeguards remain in force.

### NFS export evidence received

The supplied export list establishes a current configured NFS write route to
both media and appdata. Squashed client identities do not establish write
exclusion. The ownership plan now includes exported state/lock/control aliases,
server-side scoped denial as an adapter proposal, a private control journal,
and disposable acceptance for existing handles, reconnects, configuration
drift and uncertain outcomes. No NFS/container configuration was changed.
Gate 6 remains open: the enforcement controller and adapter are not implemented
or verified. No further production inventory request follows from this result;
isolated implementation and acceptance work must precede a production procedure.

### Disposable maintenance journal foundation

The new fixture-only maintenance journal persists ordered checkpoints with
revision checks, process exclusion and explicit release ordering. Local focused
journal, lock and production-guard checks pass (60 tests), including subprocess
death at pending checkpoints and an uncommitted interrupted transaction.
Read-only inspection never replays or clears pending history. Both authorization
and external-writer verification remain false for every fixture phase.

Unraid shfs/native durability verification is pending. This implements no NFS
or container controls, grants no move permit and closes no production gate.
The next enforcement work must bind actual controller actions and observed
outcomes to protected scope identity and persistent history.

### Maintenance journal Unraid evidence and synthetic controller

The user confirmed all 60 focused journal/lock/production-guard tests pass on
both Unraid shfs and native lab paths (10.32s and 11.15s). This verifies the
previous journal foundation on those lab filesystems, not external ownership.

The next increment adds fixed synthetic controller actions: durable request
before receipt, held lock through action/outcome, explicit release ordering,
and no replay after uncertain outcomes. Local focused checks pass 69 tests,
including subprocess exit after action but before outcome and lock replacement.
New controller checks on Unraid are pending. No real NFS/container adapter,
production permit or gate closure is introduced.

### Synthetic controller evidence and fixture scope binding

The user confirmed 69 focused tests pass on both Unraid lab paths (shfs 13.68s,
native 16.16s). The subsequent increment binds new disposable journals to their
canonical directory and directory/database identities, rejects missing scope
bindings, and independently verifies synthetic receipt identity/content before
recording completion. Local focused checks pass 81 tests, including scope and
receipt replacement failures. These new identity checks await Unraid evidence.
No external-writer exclusion or production gate is claimed; the NFS/container
enforcement backend remains unfinished.

### Scope checks confirmed; cooperative writer acceptance added

The user confirmed 81 focused scope/controller checks pass on both lab paths
(shfs 12.57s, native 14.37s). A subsequent cooperative fixture writer now checks
the durable phase for each write, including existing descriptors. Real process
tests show pending requests deny writes after controller exit and old writer
handles cannot bypass the fixture protocol. Explicit completed release is
required before cooperative writes resume. Local `--maintenance-only` checks
pass 90 tests; the new writer checks await Unraid execution.

This harness constrains only its own cooperating writer. It does not constrain
ordinary filesystem writes, NFS clients or containers, and supplies no production
ownership permit. Gate 6 and all existing production blockers remain open.

### Maintenance harness consolidated baseline through `1773d63`

The user confirmed 90 maintenance tests pass on both Unraid lab paths (shfs
21.40s, native 26.34s). The maintained consolidated integration suite also passes
locally on macOS: 475 tests and 19 subtests, using the standard runner without
publication capability flags. This exercises maintenance checks together with
migration, recovery, lifecycle, integration, JSON rescue and runtime checks.
It is not Linux publication evidence and does not replace a full Unraid run.

This completes the current synthetic maintenance-harness increment. Further
synthetic phase/receipt tests must not be reported as progress on independent
external enforcement. The next gate-6 implementation milestone is a real
deployment adapter with externally observed write denial, including existing
clients, restart control and protection API availability. A journal record,
fixture receipt or cooperative writer result cannot satisfy that milestone.

Before advancing that adapter, consolidate the current branch on Unraid using
the maintained suite on shfs and the full suite on the native lab path. The last
full native baseline remains 1,583 tests/22 subtests through `fff83c0` until a
new complete result is supplied. No production configuration/image change or
expensive Actions/build run is needed for this consolidation.

### Full Unraid baseline through `d67b7da`

The user confirmed the consolidated maintained suite passes on shfs: 475 tests
and 19 subtests in 155.29s. The full suite passes on native disposable storage:
1,650 tests and 22 subtests in 424.23s. This supersedes the earlier full-suite
baseline through `fff83c0`; prior entries remain historical evidence.

The journal/controller/cooperative-writer harness increment is consolidated.
Gate 6 still requires actual independent enforcement of external writer denial,
including NFS and container routes, existing handles, restart control and fresh
protection API availability. No additional synthetic harness milestone is
required merely to increase the test count. Production remains JSON-authoritative,
SQLite activation and deletion remain disabled, and no Actions/build/image or
service/export changes were performed for this baseline.

The operator subsequently accepted temporary unavailability of all NFS shares
as the initial adapter design. Full-service pause is selected for review, not
authorized for execution. A new read-only host probe gathers current Unraid
version, NFSD observations and service-script identities without executing any
service command. Actual service review, persistent restart prevention, isolated
server/client acceptance and independent client denial checks remain required.
