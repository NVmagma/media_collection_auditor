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
| 6. Trusted move verification | Bind identity and paths, independently prove the moved object, reject races and ambiguous outcomes | In progress: advisory identity/path checks only |
| 7. Atomic lifecycle reconciliation | Verified move clock change and intent clearance commit together; failure injection proves all-or-nothing | Not implemented |
| 8. Production lifecycle integration | Real Waiting/Holding/Keep/Removal moves use guarded ordering; existing JSON path unaffected until cutover | Not implemented |
| 9. External integrations | Arr uncertain outcomes, Jellyfin protection, dashboard authoritative reads, TV-season behavior | Not implemented |
| 10. Deployment and rollback | Disposable Unraid end-to-end tests, full CI, Docker build, backup/rollback, explicit activation approval | Not completed |

## Current decision

Five of ten *gates* have been met, but these gates do not represent equal
amounts of work. Do not publish an overall percent complete without a
documented weighting and stable denominator. Earlier 90% and 65–70% estimates
used different scopes and should not be compared or treated as reliable.

Production authority remains JSON. SQLite production activation and permanent
filesystem deletion remain disabled.

## Next engineering task

Implement and test a trusted verification contract **before** permitting
intent clearance. The existing directory fingerprints, unique-location checks,
and persisted-intent binding are advisory. A matching inode or metadata record
is not proof of a completed move, particularly across mounts or after crashes.

The verifier design must explicitly address source/destination identity,
symlink and path substitution, concurrent writers, same-filesystem rename
versus cross-filesystem copy, and what happens when identity cannot be proven.
Uncertain outcomes must remain pending for operator review. Once the verifier
is reviewed, add atomic checkpoint/intent-clearance tests with injected
failures before wiring any production move.

## Status reporting rule

For each milestone report: changed files, commit, tests executed and where,
newly completed gate (if any), remaining blockers, and whether production
behavior changed. A new test does not by itself complete a gate.
