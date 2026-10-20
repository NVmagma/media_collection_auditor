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
