# Scheduled SQLite lifecycle runs

Status: user-approved operating model, 2026-10-24. Implementation is in progress;
SQLite production activation and permanent/filesystem deletion remain disabled.
This contract supersedes host-wide writer exclusion as the Gate 6 target. Earlier
maintenance-controller, NFS, Docker and boot-fence work is retained as historical
or optional evidence, not a prerequisite for this initial scheduled model.

## User-visible behavior

Users can edit Jellyfin tags/favorites at any time. They configure a daily scan
time and an explicit IANA time zone, for example 02:00 in America/Los_Angeles.
The worker waits for the next scheduled time on startup; it does not immediately
run or catch up missed scans. Restart does not replay a previous move plan.

A scheduled run has three phases: collect the complete scan, produce a bounded
move plan, then execute eligible moves sequentially with fresh checks. No media
moves, Arr path updates or season pruning happen during collection. An incomplete
scan cannot dispatch a partial plan. Manual run semantics must follow this same
ordering; they must not provide a separate unchecked execution route.

The first schedule calculator uses a strictly future slot. Nonexistent local
times during spring DST transitions are skipped. Repeated local times during
fall DST transitions use the first occurrence only. A long run does not enqueue
missed slots; the next run uses the next future scheduled time. Persistent run
claiming must prevent duplicate execution across workers/restarts; calculating a
time alone does not provide that exclusion.

Proposed settings are `AUDIT_SCHEDULE_TIME` (HH:MM, 24-hour) and
`AUDIT_SCHEDULE_TIMEZONE` (IANA zone). They are not exposed as functioning worker
settings yet. Existing JSON scheduling remains unchanged until worker integration
is implemented and tested. The legacy interval/startup behavior must not silently
be reused for scheduled SQLite execution.

## Move-time checks and accepted concurrency

Immediately before each move, obtain fresh authoritative Jellyfin protection
information, re-evaluate the planned action, and validate the source, destination,
tracking revision and pending-operation state. Unavailable protection data, a
changed decision, an occupied destination, a changed source, or an uncertain
previous operation skips/blocks the move. A successful earlier scan is not a
protection permit. A deadline/resource cap bounds execution of a plan; expiration
requires a new scan rather than continuation from stale decisions.

Tags written after the final protection check may not prevent a move already in
progress. They apply to subsequent decisions. External writers remain active;
the scheduled time is not a maintenance fence or proof of inactivity. A concurrent
Arr update or client transfer may cause a conflict, a skipped move, or an outcome
requiring reconciliation. Do not describe metadata checks as an atomic lock on
external applications. Report a stale Arr path as pending reconciliation rather
than repeating an uncertain request automatically.

Initially implement only capability-verified same-filesystem renames with
no-overwrite publication and durable operation intents. Cross-filesystem
copy-and-delete and TV season pruning remain deferred. Unsupported filesystems
must yield an explicit skipped/blocked operation based on missing capabilities,
not a filesystem-name ban. Permanent filesystem deletion remains disabled.
User acceptance that a title might need re-downloading acknowledges the race; it
does not enable a deletion path or remove the fresh protection check.

## Crash and completion requirements

Persist intent before a move; record the observed outcome and lifecycle clock
change in guarded SQLite reconciliation. A crash or uncertain filesystem/Arr/DB
outcome leaves a pending operation for review. Do not clear the intent or retry
an operation solely because the scheduled time arrived. A host reboot does not
require disabling array autostart, Docker, NFS, SMB or Unraid management under
this model. The application must stay blocked on unresolved operations until its
recovery policy determines the next safe action.

## Revised Gate 6 acceptance

1. A full successful scan precedes all move dispatch; failed/incomplete scans
   dispatch nothing, including when a later library fails.
2. Daily scheduling respects time zone/DST, startup waiting, no catch-up and
   serialized run ownership. Invalid settings never trigger an immediate run.
3. Each candidate gets fresh protection/decision checks and source/destination
   validation. Mid-scan protection changes are covered by disposable tests.
4. Capability-verified same-filesystem rename, destination conflicts, concurrent
   source changes, crash/pending recovery and bounded batch behavior are exercised
   against disposable media. Unsupported operations retain source and state.
5. The accepted post-check tag race and external-writer limitations are visible
   in documentation and operational results. No host-wide exclusion claim is made.

Gate 7 still requires atomic lifecycle reconciliation; Gates 8–10 still require
production wiring, integration acceptance, release tests/image verification,
backup/rollback and explicit activation approval. Revising Gate 6 does not mark
it complete or authorize cutover.

## First implemented component

`app/sqlite_run_schedule.py` implements deterministic daily UTC start calculation
from a local HH:MM and explicit zone. It performs no I/O or media operations and
is not yet connected to the worker. Tests cover startup/missed-slot behavior,
exact-slot replay prevention, DST gaps/folds, fractional-hour zones, invalid
settings and naive timestamps. Next: the complete-scan barrier and bounded move
plan, followed by fresh-check execution and scheduler/worker settings integration.
