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

## Combined filesystem/service rehearsal

`app/json_readonly_scan.py` opens configured local stages with no-follow directory
handles and compares root/title identities before and after GET collection. Missing
or unsafe stages block the affected library and produce fixed issue summaries.
Overlapping/aliased roots are refused. `.DS_Store` regular files and
`.deletedByTMM` directories are reported as ignored housekeeping; neither is
removed. Unknown hidden entries and symlinks are not adopted as media titles.

TV Waiting content uses the existing bounded no-follow observation routine.
Future timestamps and unreadable/symlinked content skip the affected show.
Observed newer content proposes a reset and blocks use of the old clock; new
folders propose the current observation date without backdating. Proposals are
not applied. Successful content observations are repeated before and after
service collection. External writers are not fenced, and no result establishes
future freshness or permission to move.

`scripts/json_readonly_rehearsal.py` checks the selected offline candidate against
its verified live backup, uses that backup's captured settings/credentials only
inside the helper, and runs the combined rehearsal. Its redacted output includes
all-title reason counts, up to two proposed titles, per-library completeness and
clock-proposal counts. It verifies comparison state and archived claims remain
byte-identical. It never configures a worker, saves clocks, creates scan claims,
sends Arr updates or calls a production container control API.

The Tower check must mount production media read-only, the selected backup
read-only and only the disposable comparison directory writable for its advisory
lock. Source code is read-only, no Docker socket/host ports are mounted/published,
and the helper uses only the existing GET transports. The real auditor remains
unchanged. Changing production inventory can invalidate the rehearsal; a blocked
result is not permission to retry external actions or switch backends.

The rehearsal derives naive lifecycle time and TV descendant mtimes using the
captured lifecycle timezone (daily timezone, then TZ, then UTC). It passes an
explicit timezone only to the JSON content reader; existing SQLite callers retain
their default behavior. A Los Angeles fixture verifies that a 03:00 local content
observation remains 03:00 in the proposed clock rather than becoming UTC wall time.

### Existing configuration compatibility and local-only diagnosis

The initial Tower rehearsal returned only a generic blocked result. Source
review found two gaps in the new rehearsal: stage paths lacked the existing
MEDIA_PATH-derived defaults, and captured saved settings were stricter than the
application's known-key/string conversion rules. The rehearsal now uses those
same defaults and saved-config precedence, preserves explicit overrides, and
ignores unknown saved metadata without changing it. Boolean policy strings keep
the existing case/whitespace handling. Tests cover absent/empty path overrides,
saved JSON boolean values and unknown configuration extensions.

`--local-only` validates backup/candidate/settings, inventories media and proposes
clock observations without constructing a service collector or making network
requests. Mount the helper with `--network none` for this diagnostic. Output
explicitly reports local-only scope and network disabled; it is not service
readiness. Failures identify the last fixed diagnostic stage and a bounded error
class without exception text, paths, tokens or remote payloads. This is a new
read-only observation, not reconstruction of the earlier failed attempt.

## JSON execution foundations (not deployed)

- Archived attempt migration validates every retained entry's encoding, schema,
  timezone, date and identity before selecting the latest UTC start. Empty,
  partial or conflicting histories never initialize a fresh cooldown. Existing
  control metadata cannot be overwritten. The archive and tracking dates remain
  unchanged apart from explicit new control metadata in the isolated JSON copy.
- Clock checkpointing validates an entire proposed batch and all fresh trusted
  verification reads before saving any date. Discovery uses the current
  observation time; TV resets require an exact prior Waiting clock and a newer
  observed content date. No backdating, partial batch save, media operation or
  scan-budget reset is performed.
- The disconnected move executor pins source/destination directories, requires
  fresh protection and exact Arr source proof, journals intent, then uses Linux
  no-replace rename on one filesystem/mount. There is no overwrite/copy/delete
  fallback. It checks moved identity/content and atomically saves the destination
  clock together with the outstanding Arr sync journal before attempting the PUT.
- The existing Sonarr transport incorrectly accepted only HTTP 200 for PUT while
  Sonarr 4.0.20.3014's Accepted(id) returns HTTP 202. This is corrected to accept
  both acknowledgment shapes while still requiring two independent exact GET
  readbacks. It is a plausible cause of earlier successful-but-pending TV syncs,
  not a reconstruction of every historical incident. See the official
  [series controller](https://github.com/Sonarr/Sonarr/blob/v4.0.20.3014/src/Sonarr.Api.V3/Series/SeriesController.cs#L188)
  and [response helper](https://github.com/Sonarr/Sonarr/blob/v4.0.20.3014/src/Sonarr.Http/REST/RestController.cs#L131).
- A lost Arr acknowledgment preserves the moved clock and pending journal.
  Explicit GET-only review/acknowledgment repeats media checks and two readbacks;
  it clears only the exact selected sync, without another PUT, move replay,
  cooldown reset or fabricated historical completion.
- Move-stage recovery independently verifies whether the original folder remains
  at its source or has reached its destination. It can cancel an unperformed
  intent or record the original move clock without repeating the rename. Both
  locations present, a replaced folder, changed tracking or conflicting remote
  records retain the journal for review.
- If the folder moved but the remote record still points to its source, a
  separately reviewed action can attempt the outstanding Arr update once. The
  attempt counter is saved before dispatch, invalidating the previous review
  even after a lost response. Normal exact readbacks remain mandatory; restart
  never dispatches this action automatically.

Disposable tests exercise actual folder renames, Movie/TV slots, HTTP 202,
changing protection, occupied destinations and destination races, lost responses,
failed post-move saves and SIGKILL immediately after rename or before Arr delivery.
The native-host lab also kills a child immediately after a TV rename, records
the verified destination clock and explicitly finishes its Arr sync without
repeating the folder move. It uses only two newly created writable directories and a new
network-isolated container with loopback mock services. No production media,
appdata, credentials, templates, Docker socket, host ports or host controls are
mounted/changed. It does not activate a JSON worker or authorize permanent deletion.

## Requested final cleanup

After JSON execution/recovery, current UI/settings/integrations and state-preserving
cutover are accepted, preserve an archive in Git history and remove the old storage
implementation from this active branch. Extract genuinely shared path, schema,
protection and transport helpers into neutral modules first; keep their tests.
Remove obsolete workflows, Docker recipes, migration/release scripts, tests and
active documentation references. Replace this transition document with the JSON
operations guide. Do not delete the running service's recovery tools before
cutover, nor interpret source cleanup as permission to remove retained host
backups or rollback containers. Permanent deletion remains disabled.

## Worker clock collection integration

The disconnected JSON worker collector can now use its already-held tracking
session. It verifies local stage/title identities and TV content again before
atomically recording discoveries and episode resets, then collects services and
plans against the updated snapshot. It does not backdate discoveries, alter
unrelated clocks, move media or send Arr updates. An incomplete library saves no
partial discoveries for that library. Future episode timestamps remain per-title
blockers. The public rehearsal cannot select this checkpoint mode. Scheduling,
UI dispatch and production cutover are still pending.

## Connected JSON service candidate

The explicit `AUDITOR_WORKER_MODE=json_serialized` entrypoint now selects the
serialized JSON cycle without importing the legacy automatic worker. The default
JSON candidate image remains in preview until prepared live settings are supplied.
Missing tracking/control metadata never creates a fresh live state or scan budget.

Manual requests require administrator authentication, same-origin submission and
live confirmation. Running/queued scans reject another request; all live starts
share the persisted rolling one-hour cooldown. Daily scheduling waits for a future
slot at startup, skips nonexistent DST wall times and uses only one fall-back
slot. Settings are captured per scan, so applying ordinary settings does not
invalidate storage or change an attempt already running. Permanent deletion,
cross-filesystem moves and season pruning remain refused.

At the user's request, this candidate permits up to **five Movie moves and five TV
moves per scan**, with a total maximum of ten. Both planning and execution enforce
the per-library limits. A lower explicitly selected total cap still applies.
Increasing the existing production deployment's two-action configuration to ten
is part of the later reviewed JSON preparation; this source change does not alter
the running service. Removing the limits is a separate future decision.

Activity is retained in private JSON history across restart. All scanned decisions
are retained; the existing interface projects a bounded selection prioritizing
proposed moves. A completed move/Arr update is separate from a proposal or uncertain
operation. The settings screen uses Apply Requested Settings without a typed
confirmation phrase, while unsupported destructive policies are still rejected.
Administrator-only operation recovery repeats current local checks and exact Arr
readbacks; a reviewed sync attempt never repeats a filesystem rename.

The disposable actual-entrypoint fixture now checks a ten-move batch (five per
library), settings changes, restart, retained history and unchanged cooldown,
using synthetic media and loopback services only. No production cutover or source
cleanup is implied by these tests. Arr-import integration and state-preserving
cutover remain separate work before removal of the retained storage implementation.

## Existing-folder Arr imports on JSON

The existing administrator import interface now selects the JSON state session
when the serialized JSON worker is selected. Folder and provider/profile reviews
retain the same bounded payload checks. All imports remain unmonitored, with
movie/episode searches disabled and TV seasons unmonitored. Importing registers
an existing folder; it does not move files, reset tracking clocks or consume/reset
the scan cooldown.

The worker lock excludes concurrent scan/import dispatch. The JSON operation
journal is saved before one create request. A lost response leaves that intent
pending, blocks scans and new imports, and permits only explicit GET-based
verification/acknowledgment through Verify pending import. Changed folders,
profiles, settings or tracking invalidate a saved review. Readback mismatches
retain the intent. Tests make SQLite connections and binding calls fail if this
JSON path attempts them. The retained deployment's import path remains available
until the later cutover and source cleanup.

## Private cutover preparation

The preparation helper reads an explicitly fingerprinted current-live backup and
writes a new private directory only. It uses the latest logical tracking snapshot,
retains unknown fields and the full claim archive, and initializes the JSON
cooldown from the latest validated previous scan start. It preserves the captured
settings except for the authorized total cap of ten (five per library), switches
the runtime to the JSON worker and drops obsolete storage-specific environment
paths. Permanent deletion and cross-filesystem moves remain disabled.

Every generated file is hashed in a completion receipt. Bad image contracts,
partial claim archives, changed inputs, replaced directories and interrupted
preparations do not become complete/replayable preparations. The helper mounts
only the selected backup read-only, the source checkout read-only and its new
private destination read-write. It does not mount production media, Docker's
socket or templates, and it does not stop/start services. The receipt explicitly
leaves freshness, writer quiescence and deployment authorization unverified.

The serialized worker requires a readable, unique-key saved-settings object. A
missing/corrupt configuration pauses scanning rather than falling back from a
saved preview policy into live environment defaults. Unknown configuration fields
remain inert and are retained when applying known settings. Missing tracking is
also unavailable in the new dashboard path; it is never rendered as a fresh empty
installation or initialized automatically.

Manual requests also pin their effective settings while queued. If those settings
change before execution, the queued request is refused before admission and must
be requested again. A preview-to-live race cannot bypass the live confirmation or
expand the action cap that the administrator reviewed. This is per-request
validation; it does not bind ordinary settings to the storage release.
