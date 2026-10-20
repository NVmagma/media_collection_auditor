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
| 6. Trusted move verification | Bind identity and paths, independently prove the moved object, reject races and ambiguous outcomes | In progress: live directory witnesses and no-replace rename verified in disposable tests; concurrent-writer isolation and crash trust remain open |
| 7. Atomic lifecycle reconciliation | Verified move clock change and intent clearance commit together; failure injection proves all-or-nothing | In progress: witnessed disposable rename uses a single revision-checked reconciliation checkpoint; injected pre/post-commit failures tested. Production trust and integration remain open |
| 8. Production lifecycle integration | Real Waiting/Holding/Keep/Removal moves use guarded ordering; existing JSON path unaffected until cutover | Not implemented |
| 9. External integrations | Arr uncertain outcomes, Jellyfin protection, dashboard authoritative reads, TV-season behavior | In progress: live read-only title coverage and protection summary verified on Unraid; production freshness, Arr/dashboard/TV-season execution remain open |
| 10. Deployment and rollback | Disposable Unraid end-to-end tests, full CI, Docker build, backup/rollback, explicit activation approval | Not completed |

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
