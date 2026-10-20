# Isolated SQLite lifecycle runner contract

Branch: feature/sqlite. Production JSON authority and deletion safeguards remain
unchanged. This document does not approve activation or intent clearance in
production.

## Supported executable boundary

`app/sqlite_isolated_lifecycle_runner.py` wraps the existing disposable lifecycle
executor. It accepts only a canonical absolute marked lab directory and its
existing `state.db`. It supports explicitly named disposable title folders;
it is not a production movie/show runner. Earlier revisions supported only the
fixture named `Movie`.

The runner opens a persistent `.sqlite_runner.lock` relative to a held root
directory descriptor, refusing symlink/nonregular/hardlinked lock files. A
nonblocking flock excludes cooperating runners that use this same lock inode.
The lock is held through startup validation, durable intent, rename, witness
verification and guarded checkpoint. Close releases it on failure or process
exit. Never unlink the lock file: replacing it would let processes lock different
inodes. The runner checks held-root identity before and after execution.

Startup reads the verified SQLite revision under the lock. Any pending-intent
key, including malformed/empty pending data, stops before entering the executor.
A caller's expected revision must match. The executor retains its existing
revision, lifecycle-clock, pinned-parent, same-device, atomic no-replace rename,
live-witness and intent-binding checks. The runner adds no alternate clearance
path. Uncertain outcomes propagate without retry or replay.

## Ordered operation and failure contract

| Boundary | Required result |
| --- | --- |
| Lock unavailable | Stop before any state checkpoint or media move |
| Unmarked/unsafe root or wrong database | Stop; no operation is authorized |
| Pending intent or stale revision | Stop before entering the executor |
| Durable intent checkpoint fails | No rename |
| Crash after intent | Leave intent and original clocks; no automatic restart action |
| Crash after rename | Retain intent even if destination appears correct |
| Crash after applied checkpoint | Retain intent; caller success is not recovery evidence |
| Witness/revision/clock verification fails | No automatic intent clearance |
| Verified disposable rename | Commit destination clock and intent removal together |

## Explicit limits and production blockers

- flock is advisory. Arr, manual writers, the old rehearsal entry point and
  writers using another lock inode are not excluded. Production must establish
  writer ownership for all relevant stage directories before trusting clearance.
- Holding directory handles and comparing identity detects some substitutions;
  the isolated runner now uses descriptor-relative source/destination rename.
  Source-entry substitution and a reviewed mount/path isolation model remain
  unresolved before any production promotion.
- Same-device no-replace rename is the only executable move model. No EXDEV
  copy/delete fallback exists. Unraid share/mount behavior must be verified
  against the intended deployment; path names alone cannot establish this.
- A live directory witness is never recreated from persisted inode metadata.
  After a crash, the runner stops on the pending intent. Operator-reviewed
  recovery remains necessary; no automatic recovery clearance is added.
- The caller must keep the lab free of unrelated writers. The marker is an
  accidental-use guard, not a security boundary or proof of exclusive ownership.
- No live Jellyfin check, Arr request, dashboard cutover, season move, production
  backend selection or permanent deletion is introduced.

## Validation and next implementation

The user reported **1,025 SQLite tests passed on Unraid** through `6f348bc`, with
one non-failing Requests dependency warning. That is the baseline before this
runner increment, not evidence for the new code.

New tests verify cross-process lock contention, lock reuse and exception release,
lock ownership through executor failure, unsafe lock rejection, database binding,
pending-intent precedence and stale revisions. Linux-only tests perform a
witnessed disposable move and verify crash-after-rename leaves a pending intent
that blocks a second runner. No production directories are mounted in these tests.

Local validation: 60 related tests passed and 2 Linux move tests skipped on
macOS. Unraid validation for this increment is pending.

Next: bind rename to held parent directory descriptors and test source and
parent substitution at the actual syscall boundary. Keep this within the marked
lab runner until external-writer ownership and crash trust are resolved. Do not
rename this module as production-ready or remove the JSON backend gate merely
because its fixture tests pass. Gates 6–8 remain open.


## Descriptor-relative rename increment

The user reported **1,036 SQLite tests passed on Unraid** through `70e0eaf`,
validating the isolated-lock baseline. The next increment changes only the
isolated runner to request descriptor-relative rename. Legacy rehearsal entry
points retain their previous default behavior for regression compatibility.
Both rename entry points share the same Linux `renameat2` call, no-replace flag,
unsupported-filesystem rejection and lack of EXDEV fallback.

The descriptor primitive accepts existing directory handles and single safe
entry names only. The executor compares the source entry's identity against the
held witness immediately before invoking it. The kernel resolves the rename
against the held parents, so replacing their visible paths cannot redirect it
into replacement parent directories. Existing post-rename checks stop clock
updates and retain the intent when parent substitution is detected.

This does **not** make source identity checking and rename one atomic operation.
A writer can replace the source entry between them. A new race test deliberately
does so: the replacement may be renamed, but its identity fails the held-witness
check, tracking clocks remain unchanged and the intent remains pending. The
original witnessed fixture stays preserved. This is evidence of the remaining
writer-isolation requirement, not proof that production side effects are safe.

New Linux tests exercise successful descriptor rename, destination no-overwrite,
replacement of either held parent, unsafe entry names, and pending-intent
retention after parent/source substitution. Portable syscall-contract tests
verify the actual descriptor arguments and no fallback for unsupported kernels
or EXDEV. Local related checks: **63 passed, 17 Linux-only tests skipped** on
macOS. New Unraid validation is pending. Production activation stays disabled.

Next work: make startup and per-operation writer-ownership assumptions explicit
and bind verified state/path context throughout the runner. Until unrelated
writers can be excluded under a reviewed operational model, this runner must
remain disposable-only. No persisted fingerprint is sufficient to clear a
crashed move automatically.

## Runner binding checks

The user reported **1,054 SQLite tests passed on Unraid** through `a2d58ba`.
The next increment binds the marker, database inode and lock inode to the held
root. It verifies that the opened root matches the pre-open root identity,
opens and reads the marker relative to that directory, and rejects nonregular
or hardlinked marker/database files. Marker reads are bounded and do not follow
symlinks. Lock files remain persistent.

The lock context supplies a binding check. It compares held identities with
current entries and checks marker contents before yielding, after state loading,
when entering the executor, before intent creation, after durable intent,
after rename and before reconciliation. A normal context exit checks again.
Exceptions stop execution without automatic retry. A check failure after an
intent checkpoint retains that intent; a startup failure never enters the
executor. Post-commit check failures are uncertain outcomes, not rollback.

Tests replace the root at open, each bound file while the lock is held, and the
database during state loading. They also change marker contents without changing
its inode, reject hardlinked databases, and replace the lock after durable
intent to prove the rename is not called. Related local tests: **71 passed,
5 Linux-only tests skipped** on macOS. Unraid validation remains pending.

These are observations at execution boundaries, not continuous exclusion of
uncooperative writers. There are still windows between a check and a filesystem
or SQLite operation. Descriptor-relative rename does not atomically compare the
source entry with the witness. Neither this increment nor the marker/lock checks
satisfy production ownership, mount-isolation or recovery-clearance requirements.
The runner is still restricted to marked disposable fixtures; production remains
JSON-only with activation and permanent deletion disabled.


## Lifecycle clock request binding

The user reported **1,062 SQLite tests passed on Unraid** through `c3ee114`.
The next increment closes a pre-move validation gap: an invalid observation time
previously reached reconciliation only after a rename. The disposable executor
now rejects non-datetimes, timezone-aware values, future observations and times
predating the recorded source clock before intent creation. Omitted times still
use the current local clock. Source-clock equality is allowed.

Each flow-created durable intent records a lifecycle clock binding: source and
destination stage, original source timestamp and proposed destination timestamp.
The flow requires reconciliation to match that binding against both its request
and the current persisted source clock. An absent or mismatched required binding
leaves the intent unresolved and tracking clocks unchanged. Standalone legacy
rehearsal reconciliation remains callable without a binding only when its caller
does not require one; if a binding is present, it is always checked. This is
backward compatibility for disposable tests, not a production recovery route.

Tests prove invalid request times cannot create intent or invoke rename, missing
or changed required bindings cannot clear an intent, and a matching binding
commits the stage-clock change and intent removal in one revision. The broad
macOS run produced 1,032 passed, 21 Linux-only skips and the same 18 failures at
the existing Linux-only rename guard. No guard was weakened. New Unraid
validation is pending; the expected collection size is 1,071 tests.

This binds a request to its tracking update; it does not prove a fresh Jellyfin
observation, exclude unrelated filesystem writers, or authorize production
activation. Those remain separate unresolved integration requirements.


## Named title identity increment

The user reported **1,071 SQLite tests passed on Unraid** through `ddd71c4`.
The next increment removes the isolated runner's fixed `Movie` title assumption.
A `title_folder` argument is carried through stage lookup, duplicate-location
checks, held-source verification, descriptor rename and witnessed reconciliation.
The default remains `Movie` for existing disposable fixtures.

The isolated runner requires `media_key` to equal the folder (movie) or `TV/`
plus the folder (whole show). It rejects mismatch before creating the lock or
intent. This is the standard tracking convention, not a library/type discovery
mechanism. The shared name validator permits a single nonblank directory entry,
including spaces and Unicode, but refuses separators, dot traversal and control
characters. No filename/path sanitization silently maps one title to another.
Source and destination paths plus the media key remain bound in durable intent.
The lower-level legacy test helpers retain their synthetic-key compatibility.

New tests cover unsafe names, key mismatch and duplicates without changing the
database. Linux tests move a named movie and a named whole-show directory while
preserving an unrelated title, and verify crash-after-rename leaves the named
intent pending and prevents a second operation. Related local validation:
**95 passed, 8 Linux-only tests skipped, 1 known Linux rename test deselected**.
New Unraid validation is pending; expected collection size is 1,086 tests.

This is whole-folder execution only. It does not implement season pruning,
external integrations, Jellyfin freshness, production activation or deletion.
The next integration step is binding named execution to a revalidated advisory
lifecycle candidate, while retaining the existing revision, path and intent
checks. Arbitrary caller-supplied success or protection flags remain insufficient
for production operations.

## Plan-bound named entry point

The user reported **1,086 SQLite tests passed on Unraid** through `7509b86`.
The next increment adds `run_isolated_planned_move`, a stricter named execution
entry point. The manual isolated runner remains a lower-level fixture tool.
Neither entry point is connected to production.

The shared disposable candidate validator is reused by both the earlier strict
rehearsal entry point and the new isolated planned runner. It requires a
non-authorizing advisory plan, an integer source revision, exactly one matching
media-key row, matching source/destination stages, candidate status and the full
required-check list. It does not mark those checks as independently satisfied.
The new entry point detaches the plan bundle, requires a naive plan clock and
uses that clock for the tracking update; an explicitly different observation
time requires replanning. It carries the plan revision into locked execution,
where current SQLite revision and unresolved-intent checks retain precedence.

The existing executor recomputes the lifecycle plan from the detached time,
thresholds and caller-supplied signals before durable intent or rename. Changed
candidate rows, candidate counts or revisions block execution. No-op, unavailable
protection or unplanned destinations cannot become move candidates. Named folder
binding, root/marker/database/lock checks, held parents, live witness and durable
clock binding all remain in force. A plan is still advisory evidence, not a
fresh Jellyfin observation or proof of exclusive external-writer ownership.

New tests cover absent/malformed plans, changed protection/threshold inputs,
stale revisions, required-check tampering, duplicate rows, unplanned destinations
and mismatched plan clocks. A portable injected-crash test proves a named plan
creates durable bound intent and a subsequent run refuses replay. Linux tests
execute matching Holding and protected Keep candidates on disposable payloads.
Related local tests: **60 passed, 10 Linux-only skipped, 1 known Linux move test
deselected**. Unraid validation is pending; expected collection size is 1,101.

Next integration work is live signal collection/revalidation for the planned
runner, including a clear expiry policy and title/observation binding. A plan's
stored time or successful report must not be relabeled as independently verified
freshness. Season-level behavior, Arr outcomes, dashboard authority and actual
production cutover remain separate open requirements.


## Collected protection in the isolated runner

The user reported **1,101 SQLite tests passed on Unraid** through `57fd06b`.
The next increment adds `run_collected_isolated_move`, a callable experimental
entry point with a trusted caller-supplied GET transport. It holds the existing
lab lock, checks pending intents before network requests, collects a complete
unambiguous title observation, and builds the candidate from the real lifecycle
decision/plan functions. Movie/Series type, folder and standard tracking key must
agree. Thresholds are detached from caller mutation.

Immediately before durable intent creation, a callback collects the title again
without reusing the first scan's response cache. Both observations must have the
same logical item ID/path and identical aggregate signals. Missing user/title
coverage, ambiguous identities, request errors or any changed signal stop before
intent and require a new invocation. Source/destination stage choice comes from
the collected candidate; it is not an arbitrary caller destination.

A 1–60 second budget covers the first scan, planning and second scan. Both a
monotonic elapsed-time check and local-clock checks enforce the budget and reject
clock reversal. The second scan must finish within that window. Root binding
and held parents are checked again after the callback, and coordinator revision
verification catches state changes during refresh before intent creation. No
failed observation is converted into an all-false signal set.

New fixture tests cover changed protection/favorites, identity replacement,
disappearing titles, transport failure, expiry during either scan, timer reversal,
pending-intent precedence, state changes during refresh, and two successful scans
before an injected post-intent crash. Linux tests execute unprotected Holding
and keep-forever Keep candidates using disposable payloads. Related local tests:
**104 passed, 12 Linux-only skipped**. New Unraid validation is pending; expected
collection size is 1,115 tests.

This is a bounded experimental collection policy, **not** proof of independently
verified production freshness. The trusted transport could itself cache or lie;
Jellyfin can change after the last response and there is no server transaction
spanning the move. External filesystem writer exclusion remains unresolved.
No live moving CLI, production activation, Arr request, season pruning or
permanent deletion is added. The Docker regression command uses fake transport
and disposable media, with no Jellyfin credentials or production mounts.

## One-shot isolated Arr delivery

The user reported **1,115 SQLite tests passed on Unraid** through `58b3b8b`.
The next increment adds a separate `deliver_isolated_arr_request` rehearsal. It
has no HTTP implementation or production caller: `send(details)` is an explicit
trusted test transport. It is restricted by the same marked-root lock and
binding checks, with the database fixed to that root's `state.db`.

Before sending, the runner requires a matching existing `arr_sync_pending`
entry, destination lifecycle clock, one unique safe title directory in the
queued stage, service/key agreement (Radarr movie or Sonarr TV key), positive
integer Arr ID, canonical absolute remote root and strict boolean monitoring
state. It accepts only service, title_id, root and monitored request fields;
credentials or arbitrary extra request fields are rejected, not persisted.
The existing response inspector now shares the extracted request-shape validator.

The runner checkpoints an `arr_sync` intent before calling `send` once. A strict
boolean True response is recorded as `acknowledged_unverified` in phase
`applied_pending_reconciliation`. False, None and other response shapes remain
`unknown_response`; exceptions become `request_exception_unknown`, without raw
exception text. Unknown phases remain `intent_recorded`. The outcome update is
revision-checked; checkpoint uncertainty propagates and does not trigger retry.
Every result leaves both intent and queue entry in place. A restart sees pending
intent and refuses another send, including after apparent acknowledgement.

New fixture tests prove durable ordering inside the send callback, no replay
for all response categories, crashes before/after send, queue and destination
mismatch refusal, no send after intent-checkpoint failure, and no replay after
an outcome checkpoint fails either before or after committing. They verify
preservation of lifecycle clocks and queue state, detached callback arguments,
and secret-field rejection. Related local tests: **88 passed, 8 Linux-only
skipped**. New Unraid validation is pending; expected collection size is 1,130.

This foundation does not yet enqueue notifications atomically with move
reconciliation, authenticate an Arr service, verify that a supplied Arr ID
belongs to the local title, fetch the remote result, or authorize intent
clearance. Those are remaining integration work, not implied by a send callback
return value. It does not change the production JSON retry implementation.
No real service requests or production mounts are used by regression tests.


## Atomic move-to-Arr handoff

The user reported **1,130 SQLite tests passed on Unraid** through `df44671`.
The next increment accepts an optional non-secret `arr_sync_request` in the
isolated/planned/collected move flow. The request is validated against the media
key, folder, service and destination stage and detached before execution. An
existing queue entry blocks the move before intent rather than being replaced.
The durable move intent carries the request alongside path and clock bindings.

After witnessed rename, reconciliation requires the request to exactly match the
persisted intent. One revision-checked transaction changes the stage clock,
adds `arr_sync_pending[media_key]`, and clears the move intent. The queue entry
contains stage, service, title_id, root and monitored. Those extra stable identity
fields are preserved by the existing snapshot contract. Arr delivery checks them
when present; legacy queue entries without stable IDs retain their earlier
experimental handling. A supplied ID is still not independently verified title
identity merely because it is persisted.

The commit never sends an Arr notification. The separate one-shot delivery
runner consumes the queue after the move commit and still leaves every outcome
pending verification. A crash between move commit and delivery preserves the
queued work. A crash/uncertainty at final move commit requires reopening state:
either the old clock and move intent remain, or the new clock and queue exist
with no move intent. No automatic move replay is authorized in either case.

New portable tests prove the queue/clock/clearance share exactly one revision,
pre- and post-commit errors never create a partial handoff, changed or missing
bound requests cannot clear intent, and existing queues cannot be overwritten.
They also reject queued Arr ID substitution and block moves with preexisting
notification work. A Linux end-to-end fixture collects protection, moves a named
title to Keep, verifies atomic queue creation, then performs one fake Arr send
that remains acknowledged-but-unverified. Related local validation: **94 passed,
13 Linux-only skipped**. Unraid validation is pending; expected suite size 1,140.

No actual Arr HTTP integration, independently fetched remote identity/outcome,
production runner, season pruning or deletion is introduced. Request omission
means no new queue is created, preserving existing fixture behavior; production
integration must explicitly select and verify its external-sync policy.

## Held-descriptor mount binding increment

The user reported **1,140 SQLite tests passed on Unraid** through `ac9ae6d`.
The documentation-only gate assessment `d3598a4` changed no executable code.
The next increment requires matching Linux mount IDs and devices for the held
source parent, destination parent and source witness in descriptor-bound
execution. Namespace/directory observations are persisted in intent for
inspection but never authorize restart recovery. Checks repeat before intent,
after refresh, after intent/rename and before reconciliation.

Portable tests cover malformed/duplicate mount fields, same-device/different-
mount rejection, namespace/mount changes, unavailable mount data before intent,
and changed mount binding after intent blocking rename. A Linux test reads the
actual kernel descriptor records. Related local tests: **67 passed, 14 Linux-only
skipped**. Unraid validation is pending; expected suite size 1,153 tests.

See [the blocked production trust contract](sqlite-production-move-trust-contract.md)
for the supported first execution model, external-writer requirements and crash
policy. No ownership flag or persisted mount witness can bypass those blockers.
