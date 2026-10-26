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

## Crash-window matrix: unknown external outcome

Additional checkpoint-only regressions simulate a process disappearing after
an external action might have been attempted, with no applied checkpoint, and
a rejected applied checkpoint before SQLite writes. Both `move` and `arr_sync`
retain the recorded intent and refuse a second operation or reconciliation.
The tests deliberately do not perform an external action, so they cannot
establish filesystem or Arr outcomes. Actual interrupted-action behavior
remains a separate disposable-media acceptance gate.

## Disposable-file rehearsal design

The proposed isolated fixture contract and crash-window matrix are documented
in [SQLite disposable move rehearsal](sqlite-disposable-move-rehearsal.md).
This is a reviewable plan only: no move-executing lab script has been enabled,
and approval is required before the isolated rehearsal runs.

## Disposable-file crash-window integration tests (automated)

The test suite now performs a **real rename of test-created bytes inside
pytest temporary directories** after a durable SQLite move intent, then
reopens the SQLite database. It covers before intent, after intent, after
rename, and after applied checkpoint; it also tests both-present and
both-missing ambiguous file states. Every pending operation blocks replay,
and even the applied phase refuses reconciliation. No production media,
Unraid mounts, external APIs, or deletion are involved. These automated
filesystem tests are not the separate operator-reviewed `/lab` container
rehearsal; that gate remains open.

## Directory move recovery integration matrix

A second automated integration matrix uses **real disposable directory
renames** inside pytest temporary directories. It combines captured
pre-move directory evidence, durable SQLite intent, actual rename, optional
applied checkpoint, restart, read-only filesystem classification, and
operator-facing recovery status. It covers source-only, destination-only,
applied-but-unreconciled, both-present, and both-missing states. All results
must remain blocked, JSON authoritative, and SQLite revision unchanged by
inspection. These tests are not a process-kill or container-recreation test,
and do not satisfy the separate isolated Unraid `/lab` acceptance gate.

## Separate-process disposable directory interruption matrix

A fresh Python subprocess now records the SQLite intent, optionally renames
an isolated disposable directory, and optionally checkpoints the applied
phase. The worker exits; the parent process independently reopens SQLite,
checks persisted phase and filesystem classification, verifies read-only
inspection does not alter revision, and confirms retry remains blocked.
The three windows are after intent, after rename without applied checkpoint,
and after applied checkpoint. These are clean process exits at deliberate
interruption boundaries, **not forced SIGKILL, mid-syscall interruption, or
container recreation**. They do not authorize recovery or activate SQLite.

## Offline migration and rollback parity matrix

Automated disposable JSON-to-SQLite round-trip tests now cover empty state,
all four lifecycle tracking sections, Arr retry entries, and unknown legacy
fields. Each verifies exact source/backup JSON bytes and SQLite content;
removing the experimental database from service leaves the authoritative
JSON intact. Additional tests reject source changes after backup and
ambiguous duplicate JSON keys. This is **offline copy/rollback parity only**,
not permission to cut over or a full Unraid backup-restore rehearsal.

## Isolated lifecycle state persistence matrix

Additional disposable SQLite tests exercise guarded checkpoints for each
lifecycle tracking section, retention of unrelated historical sections,
unknown legacy fields, and all three Arr retry stages. A stale second
writer attempting to place a title in Removal after another writer saved
Keep must fail without overwriting the committed Keep state. Original JSON
and backup bytes remain unchanged. These tests establish **storage-level
persistence parity only**: actual Jellyfin tag/favorite protection decisions,
full media lifecycle execution, and Unraid restart tests remain separate
acceptance gates. No production SQLite activation is authorized.

## Jellyfin read-only recovery protection matrix

Mocked HTTP integration cases now exercise protected movie and series
identities, title-level and season-level `keep-forever`, `keep`,
`keep-all-seasons`, `not-at-all`, favorites, and missing user scope.
The current recovery inspector deliberately refuses reconciliation for
**all** of these cases because complete protection evidence is not yet
transactionally verifiable. The tests verify unchanged JSON, SQLite revision,
and durable pending move. This is **fail-closed recovery parity**, not proof
of correct live lifecycle routing for each tag. That requires a separate
production-logic parity suite before cutover.

## Forced process termination recovery matrix

A separate POSIX Python worker now receives real `SIGKILL` after each of
three deliberate crash boundaries: durable intent, filesystem directory
rename, and applied checkpoint. The parent process independently reopens
SQLite, verifies the persisted phase and blocked read-only filesystem
classification, and confirms no automatic retry. These are actual forced
process terminations, but **not** kernel power-loss simulations or Unraid
Docker container restart/volume-remount acceptance. Only disposable pytest
paths are affected; production JSON remains authoritative.
