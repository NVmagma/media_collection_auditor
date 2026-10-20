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
| 6. Trusted move verification | Bind identity and paths, independently prove the moved object, reject races and ambiguous outcomes | In progress: cooperating-runner lock, held-parent rename, root/marker/database bindings and adversarial substitution tests pass on Unraid. Persistent Unraid lab run rejects required no-replace rename (EINVAL); source-entry races, external-writer ownership and production crash trust also remain open |
| 7. Atomic lifecycle reconciliation | Verified move clock change and intent clearance commit together; failure injection proves all-or-nothing | In progress: Unraid tests verify one transaction for destination clock, stable Arr queue entry and move-intent clearance, including pre/post-commit uncertainty. Completion still depends on gate 6 and production integration |
| 8. Production lifecycle integration | Real Waiting/Holding/Keep/Removal moves use guarded ordering; existing JSON path unaffected until cutover | Not wired: named, plan-bound, collected-signal isolated execution exists, but production audit paths still reject SQLite |
| 9. External integrations | Arr uncertain outcomes, Jellyfin protection, dashboard authoritative reads, TV-season behavior | In progress: 539-title live advisory coverage verified; bounded two-scan protection and one-shot Arr unknown outcomes tested on Unraid. Remote Arr identity/outcome verification, dashboard authority and TV-season execution remain open |
| 10. Deployment and rollback | Disposable Unraid end-to-end tests, full CI, Docker build, backup/rollback, explicit activation approval | Incomplete: disposable Unraid suite passes (1,140 tests through ac9ae6d). Final release CI/image, rollback after advanced SQLite state and explicit activation approval remain open |

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
