# SQLite recovery acceptance review — 2026-10-19

**Scope:** experimental `feature/sqlite` only. This document is a gap review,
not a deployment authorization. Production JSON remains authoritative. Automatic
reconciliation and permanent filesystem deletion remain disabled.

## Evidence already exercised

| Requirement | Evidence | Limit |
| --- | --- | --- |
| Revisioned SQLite snapshots and operation checkpoints | Unit tests and offline restart lab rehearsals | No production write cutover |
| Pending intent persists after container recreation | Unraid isolated lab create/verify gates | No actual interrupted media operation |
| Source-only, destination-only, both-present, both-missing | Four blocked filesystem inspection scenarios | Presence is not identity |
| Malformed, changing, or unavailable evidence | Fail-closed regression tests | Repeated reads are not an atomic filesystem snapshot |
| Mount namespace/path observations | Local mountinfo and three-service advisory diagnostics | No independent cross-container mount attestation |
| Jellyfin/Arr identity observations | Existing read-only recovery identity modules/tests | Live observations cannot alone authorize replay |
| CI safety and Docker workflows | Previously confirmed passing on `feature/sqlite` | Not equivalent to isolated end-to-end failure injection |

## Remaining acceptance gates (in priority order)

1. **Disposable-media crash windows:** in a strictly isolated lab, exercise
   interruption before durable intent, after intent, during move, after move,
   and before/after reconciliation checkpoint. Each case must retain tracking
   state and block ambiguous retries. No production media mounts or credentials.
2. **Recovery decision contract:** document independent evidence requirements,
   service identity freshness, source/destination object binding, mount namespace
   trust boundaries, and operator action. Do not introduce automatic clearance
   merely to complete a test.
3. **Migration parity and rollback:** verify lossless JSON migration, historical
   timestamps and unknown fields, concurrent access, WAL durability, dashboard
   consistency, and a tested return to authoritative JSON without state loss.
4. **Lifecycle parity:** run Waiting, Holding, Keep, Removal, Jellyfin protection,
   and Arr synchronization against disposable fixtures. Verify fail-closed
   behavior on unavailable Jellyfin information and that deletion stays off.
5. **Controlled Unraid rehearsal:** repeat the approved isolated lab checklist,
   review exact Compose mounts and credentials, test restart and backup restore,
   and verify both GitHub Actions workflows. Do not update production containers.
6. **Explicit production approval:** a separate operator decision is required
   before enabling SQLite or changing production storage authority.

## Next incremental task

Design a **non-destructive crash-window matrix** and its disposable fixture
contracts before writing any move-executing test. Require review of mounts,
container privileges, and test boundaries before execution. The first tests
should validate checkpoint behavior without moving files.

## Estimate

The prior conversational estimate of approximately 82% is an informal planning
estimate, **not** a measured acceptance percentage. The roadmap previously
reported 78% and was stale. Progress should be described by acceptance gates
rather than treating a percentage as a safety certification.

## Crash-window matrix: checkpoint-only stage

The first crash-window matrix now exercises both `move` and `arr_sync`
intents using isolated SQLite fixtures. It covers a write rejected before
checkpoint, restart after intent but before any external action, and restart
after an applied checkpoint. Existing tests also cover lost acknowledgement
after durable intent and applied writes. These tests **do not perform any
filesystem moves or contact external services**. An interruption during an
actual move, real media identity verification, and independent recovery
clearance remain untested and blocked until a separately reviewed disposable
lab plan is approved.
