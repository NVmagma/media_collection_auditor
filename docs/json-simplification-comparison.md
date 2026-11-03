# JSON simplification comparison

Decision approved: evaluate a simpler JSON implementation with the current UI
before any production backend change. Active work remains on feature/interface-api.
Production is still SQLite live, with permanent deletion disabled.

## What the source review found

| Area | Existing capability | Work needed |
| --- | --- | --- |
| Dashboard, posters, Jellyfin links | Current web layer has a JSON read path | Verify modern pages against the exported latest snapshot |
| Lifecycle state | JSON loader retains unknown fields; saver uses temporary file, fsync, atomic replace; run lock exists | Explicit existing-install mode must refuse missing state; verify duplicate/nonfinite JSON rejection and safe error handling |
| Worker | Legacy collection_auditor remains available | Do not activate it unchanged: automatic pending Arr retries and different scheduler/cap behavior must be removed or adapted |
| Jellyfin | Modern paginated, verified collector exists in scheduled modules | Reuse working authentication/pagination/matching; do not revert to old collection queries |
| Scan controls | SQLite coordinator owns hourly claims and per-library caps | One worker, one-hour cooldown, one Movie/one TV limit; carry forward claims rather than reset budget |
| Arr imports | New UI/transport can be retained | Controller currently requires live SQLite binding; adapt persistence before enabling JSON imports |
| Settings | Modern settings flow is tied to SQLite binding/application | Retain interface; ordinary valid configuration changes should not require release rebinding |
| Crash recovery | SQLite intent protects filesystem/HTTP uncertainty | Retain a small durable operation journal; independently report folder move and Arr sync outcomes; never blindly retry uncertain HTTP |
| Coverage | Detects absent folders, missing dates, housekeeping directories | Display actionable discrepancies; never invent dates or delete tracking based solely on absence |

The observed failures do not establish SQLite corruption. Integration failures
and uncertain acknowledgments must be handled under either backend. JSON reduces
operational complexity only if the surrounding lifecycle and recovery flow is
also simplified. Do not replace the old worker's state adapter and assume parity.

## Staged acceptance

1. Review and explicitly reconcile the current pending Arr operation on Tower.
   Capture a fresh complete logical backup afterward. The retained original JSON
   is stale and must not be used as the migration source.
2. Prepare **offline comparison inputs** from that selected verified backup.
   `scripts/json_comparison_candidate.py` copies tracking-snapshot.json byte for
   byte to a fresh private auditor_state.json and archives scan claims separately.
   It does not select a backend, install credentials/settings, start a container,
   reset claims or write any existing state. Its completion manifest records the
   source revision and hashes, not a deployment permission or freshness claim.
3. Run the current web UI against disposable JSON state with external services
   stubbed; compare visible records, dates, widgets and navigation with SQLite.
4. Implement a simple serialized worker around the existing proven collector and
   policy, with atomic JSON snapshots and a durable operation journal. Settings
   changes affect subsequent scans; a running scan uses its captured settings.
   Missing Arr records skip the affected title and explain why. Uncertain sync
   pauses affected work and remains visible without taking the whole UI down.
5. Exercise tag/favorite protections for every user, TV whole-show behavior,
   discovery, per-library limits, cooldown across restart, unavailable services,
   duplicate paths, lost acknowledgments, interrupted moves and interrupted saves
   on disposable media. Keep deletion and season pruning disabled.
6. Compare failures and recovery steps against the simplified SQLite option.
   Select the less burdensome design using evidence. Only then prepare a fresh,
   reviewed production cutover with a quiescent latest snapshot and rollback.

## First implementation boundary

The candidate builder uses the existing verified live-backup reader. It refuses
partial/corrupt/incorrectly selected backups and pending operations. Each run
creates a new private candidate; interrupted candidates remain incomplete. Scan
claims are archived **not activated**: a later worker must explicitly translate
and verify cooldown continuity before live acceptance. It is not a JSON release.
No production files or services are changed by the development tests.

## Reader comparison progress

The current selected JSON dashboard reader and authenticated Homarr endpoints
have been tested with 541 synthetic Waiting records plus Movie/TV Holding, Keep
and Removal records. Every timestamp and unknown state field remains intact;
public projections omit private extensions. Both library filters match the same
snapshot projection, and the ten-item widget limit does not cap collection totals.
The current dashboard and separate Review page render from JSON without SQLite
reads or external requests. Corrupt/missing JSON keeps integration responses
unavailable and does not recreate state. These tests do not establish worker,
settings-application or Arr-import parity and do not authorize a backend switch.

Tower's offline candidate was prepared from the post-reconciliation backup at
source revision 11: 554 Waiting records, seven Holding, two Removal, 15 Keep,
zero pending Arr updates, and 14 archived scan claims. That is a point-in-time
comparison input, not a current production backup or inventory freshness claim.

## Isolated worker storage foundation

`app/json_tracking_store.py` is not wired into the entrypoint. It provides an
explicit session over one existing JSON file, holding the existing shared audit
lock for the session and writing only when checkpoint is requested. Checkpoints
write a private temporary file, fsync, replace atomically and fsync the directory.
Unknown fields and original lifecycle timestamps survive. Exiting or raising an
exception does not implicitly save partially modified in-memory state.

Missing/invalid state, duplicate keys, nonfinite extension values, unsafe links
and intervening file replacement are refused. Cooperative concurrent processes
are blocked by the lock. This does not fence noncooperating external writers or
make filesystem moves and Arr HTTP atomic. A checkpoint exception after replace
is uncertain: it must not trigger replay of an external action. Operation-journal
and scan-admission integration remain subsequent worker work.

Disposable Linux tests cover two-process contention, failures during replacement
and actual SIGKILL immediately before/after replacement. Restart reads a complete
old/new snapshot; abandoned temporary files are not adopted. The builder and
reader comparison remain separate from production selection or activation.

## Isolated scan control and operation journal

`app/json_scan_control.py` remains disconnected from production. It holds the
JSON session lock for the whole scan and checkpoints the attempt start before
returning control to a future worker. Manual and scheduled starts share a rolling
3600-second cooldown stored in the same JSON file. Restart and clock rollback
cannot reset it. Normal settings changes do not require a storage binding.

Control initialization is explicit, cannot overwrite existing metadata or pending
operations, and requires the separately verified latest old scan timestamp. The
archived Tower claims have **not** been translated or activated. That migration
proof and scheduling/due-slot integration remain required before a live worker.

The journal checkpoints a single move/Arr intent before permitting an executor
to act. Clearing it requires the exact operation identifier and a trusted local
fresh-outcome verifier; browser-supplied booleans are not such verification.
Wrong IDs, false/failed verification and tracking mutation during verification
leave the durable journal intact. No recovery endpoint or media/HTTP executor is
provided by this module. Restart never replays a journaled action automatically.

An interrupted scan without a pending journal may start a fresh scan after its
cooldown. An unresolved journal requires review. Completion is explicit and
refused while an operation is pending; simply returning from a context is not
reported as completion. A failed atomic checkpoint invalidates that session so a
caller cannot continue external work after an uncertain state save.

Tests include competing processes, manual/scheduled cooldown across reopened
state, explicit initialization, clock rollback, pending legacy operations, lost
verification acknowledgments, and actual SIGKILL with/without an operation.
Per-library action selection, fresh protection checks, remote readback routines,
recovery UI and schedule handling remain worker integration work.

## Read-only lifecycle planning

`app/json_lifecycle_plan.py` is a pure advisory planner, not a worker or authority
check. It accepts detached, complete adapter observations and reuses the existing
lifecycle decision function and reason contract. It validates the snapshot once,
then checks clocks per title without rescanning the whole snapshot for each row.
The future adapter must prove collection completeness and exact Arr path matches;
fixture flags alone do not establish either, and execution must refresh evidence.

Selection currently reserves one Movie and one TV proposal. Missing Arr records,
conflicting paths and ambiguous records skip the affected title without consuming
a slot; the next eligible title can be proposed. Incomplete Jellyfin/Arr library
collection blocks that library's proposals. Incomplete signals or missing clocks
never become permission to move. Protected/favorite/keep TV decisions remain
whole-title decisions; no season pruning or permanent deletion is proposed.

The planner retains every decision up to the explicit 100,000-title total bound.
Exceeding the bound refuses the plan instead of returning an apparent complete
partial scan. Presentation pagination is still separate work. Tested 541-title
observations preserve all rows and dates. No journal, scan claim, tracking date,
folder or external catalog is written by planning. These changes are not wired
to the running SQLite service or the legacy JSON worker.

## GET-only collection integration

`app/json_scan_collection.py` connects the existing bounded Jellyfin GET
transport, complete per-user pagination/BoxSet handling and Arr v3 catalog GETs
to the JSON advisory planner. Each invocation detaches settings and snapshot,
creates fresh scan-scoped catalogs and retains no credentials or raw service
responses in its report. Selected provider matches remain non-authorizing.

Actual loopback HTTP tests cover 129 movies plus two shows, two Jellyfin users,
second-page collection, second-user favorites/failures, changing pagination,
missing/conflicting/ambiguous Arr mappings and failed Sonarr/Jellyfin reads.
Only GET requests are sent. Arr trailing-slash compatibility remains reused.
One catalog per library per scan is sufficient; there is no retry after failure.
New scans reread protections rather than reusing the previous scan's cache.

This is a complete **service collection rehearsal with supplied synthetic local
inventory**, not production inventory verification. Local root/title descriptor
validation, TV episode clock reset/discovery and before-move fresh checks still
need worker integration. The result explicitly leaves independent inventory and
freshness unverified and grants no media action authority. No scan claim or state
file is modified by collection. A malformed inventory or pending journal fails
before requests, and exceeding the whole-run deadline returns no partial plan.
