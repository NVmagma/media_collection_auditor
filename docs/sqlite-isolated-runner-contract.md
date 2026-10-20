# Isolated SQLite lifecycle runner contract

Branch: feature/sqlite. Production JSON authority and deletion safeguards remain
unchanged. This document does not approve activation or intent clearance in
production.

## Supported executable boundary

`app/sqlite_isolated_lifecycle_runner.py` wraps the existing disposable lifecycle
executor. It accepts only a canonical absolute marked lab directory and its
existing `state.db`. The existing executor still restricts media to the lab's
fixture named `Movie`; it is not a general-purpose movie/show runner.

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
  it does not make path-based rename immune to races. Descriptor-relative
  source/destination operations and a reviewed mount/path isolation model are
  still required before any production promotion.
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
