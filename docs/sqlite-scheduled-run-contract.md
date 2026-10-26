# Scheduled SQLite lifecycle runs

Status: user-approved operating model; Gate 6 core acceptance completed 2026-10-24.
Production integration remains in progress;
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
settings and naive timestamps. The complete-scan barrier and bounded advisory move plan are also implemented in
`app/sqlite_scheduled_plan.py`. Every configured collector and its iterator must
finish before the existing lifecycle decision bridge runs. Later-library or
pagination exceptions expose no partial plan. Pending operations, duplicate media
identities, title-limit overflow and scan deadlines block planning. Action caps
limit the plan without shortening collection. Detached snapshot/signal inputs and
immutable move records prevent later collector mutations from changing the plan.
Missing protection data blocks that title; Removal never proposes deletion.

The injected collector remains responsible for complete pagination and genuinely
authoritative observations; this interface is not proof of live Jellyfin freshness.
There is no move/Arr/persistence callback or production runner connection here.
An advisory plan records its tracking revision/source clocks for later checks;
those records do not prove the revision stayed current during collection. Next:
fresh-check execution with current revision/path validation, durable intent/outcome
integration and plan expiration, then scheduler/worker settings integration.


## Fresh per-move advisory recheck

`app/sqlite_scheduled_recheck.py` now reads tracking before and after invoking a
fresh protection-provider call. It rejects plan nonmembers, different processes,
expired/regressing monotonic time, changed revisions/clocks, pending operations,
conflicting stages, incomplete/inconsistent signals and changed lifecycle
decisions. The original favorite policy is retained in the plan. All six existing
signal fields must be explicit booleans; an empty dictionary is not a fresh clear
protection response. Provider exceptions are redacted from the report.

Plans carry their creating process ID and monotonic collection deadline; that
same deadline also bounds recheck. A separate short protection budget includes
tracking checks surrounding the refresh. These ephemeral plans are not restart
recovery records and must not be deserialized/adopted after restart. Successful
rechecks remain `revalidated_advisory`, with filesystem validation and guarded
intent handling explicitly required. The injected read-only protection provider
must genuinely query authoritative data; a callback invocation alone does not
prove it bypassed caches or established complete user/title coverage.

Execution remains unwired. Before moving, implement source/destination capability
checks and durable intent/outcome reconciliation. A completed move advances the
tracking revision, so a future serialized executor must validate a guarded revision
chain for subsequent candidates; it must not simply relax the original plan's
revision comparison. Existing production cutover guards still block activation.


## Scheduled disposable rename integration

`app/sqlite_scheduled_disposable_executor.py` connects one advisory scheduled
candidate to the existing marked disposable SQLite lifecycle flow. It holds the
cooperating runner lock, validates the requested title/database binding, performs
a fresh advisory recheck before intent, and requires that exact pending intent
and revision immediately before rename. Evidence hashing and intent persistence
must finish within the protection and plan deadlines; expiration retains intent
and blocks rename. Held stage directory descriptors, same-mount/device binding,
atomic no-replace rename and live post-rename witness checks remain in force.
Both parent directories are fsynced before lifecycle reconciliation. No copy,
source deletion, Arr delivery, restart replay or production activation is exposed.

Local Linux/Python 3.12.15 acceptance passed 12 scenarios in a new cached-image
container with no host mounts, network or added capabilities. Real rename and
clock/intent reconciliation passed. Other scenarios cover fresh protection,
missing protection, pending failures before/after rename, existing and racing
destinations, source replacement during refresh, expiration after intent,
unsupported rename and parent sync failure. An actual SIGKILL immediately after
the durable intent checkpoint left the source and pending intent intact; a later
attempt did not replay it. The fixture container was removed after acceptance.
This is local Linux evidence, not Tower filesystem acceptance.

Source-entry identity is checked before the rename and witnessed afterward.
This is not an inode-conditional syscall and does not prevent a writer replacing
the source entry in the final gap. Such post-check races remain an acknowledged
concurrency limitation; detected uncertain outcomes retain intent instead of
clearing it or rolling back another writer's data. These checks also do not
establish absence of open writers inside the moved directory.

The adapter handles one candidate, not a production batch. Reusing its original
plan after a successful move is stale and must fail. Remaining integration:
guarded batch revision chaining, authoritative provider wiring, production stage
roots/capability acceptance, explicit pending-operation review, scheduler/worker
settings, and production cutover assessment for this revised model. No further
host-wide exclusion/boot permission probes are needed for the scheduled model.


## Revision-chained disposable batches and collector adapter

`app/sqlite_scheduled_disposable_batch.py` now holds one cooperating runner lock
across a single-library batch. It verifies initial revision/pending state, invokes
the fresh-check rename adapter for each candidate, and accepts only the exact
expected lifecycle snapshot at revision +3 (intent, applied, reconciliation).
Only that verified result advances the ephemeral plan's revision. It does not
rebase against arbitrary newer state. Unexpected metadata/revision changes stop
the batch. The original plan cannot replay a completed batch.

The batch report distinguishes verified completed entries from the stopped
candidate. A stopped candidate may already have moved; no replay/clearance is
implied. Earlier verified moves remain committed. Protection changes, unavailable
providers and post-intent uncertainty stop remaining candidates. No rollback or
automatic retry is attempted. Action caps leave unplanned source titles alone.
The disposable adapter binds one stage tree/library; multi-library production
root routing and one run-wide action budget remain to be integrated.

`app/sqlite_scheduled_jellyfin.py` binds title keys/types/folders to the existing
Jellyfin collector, invoking user enumeration and complete page collection on
every candidate refresh. It stores no signal cache. Missing coverage, ambiguous
matches, transport failures and invalid responses return unavailable protection.
Bindings are detached from caller mutations. The collector currently uses the
default tag names; custom tag settings must not silently use this adapter. A
production transport with timeouts/credentials and library/path identity binding
still needs integration and acceptance; injected transports are not independent
proof of live freshness.

Local Linux/Python 3.12.15 acceptance now covers 20 scenarios, including two
successful chained moves, a saved second title, second-operation failures before
and after rename, caps, a competing cooperating runner, an unexpected writer
changing tracking after completion, and an integrated collector refresh that
sees a new keep-forever tag after the scan. These extend the earlier 12-scenario
acceptance. All are disposable; no production behavior or gate status changed.


## Final core integration and acceptance boundary

The [Gate 6 acceptance record](sqlite-gate6-scheduled-acceptance.md) now owns the
current exit checklist. Earlier progress subsections above describe intermediate
states; batch chaining, configured-root observations, transport, pending review
and slot orchestration are now implemented and locally verified.

`sqlite_scheduled_disposable_run` retains one cooperating runner lock from the
durable slot claim through full collection and batch execution. Daily zone/date
claims use exclusive creation plus file/parent fsync; failed or partial claims
remain and are never replayed automatically. Claims suppress duplicate scheduled
attempts for the same zone/local date, even after an in-day time-setting change.
They are not move permits or proof against hostile storage modification.

`sqlite_scheduled_transport` supplies GET-only network requests with explicit
credentials, no proxy inheritance/redirects/retries/signal cache, bounded bodies,
request counts and socket/read budgets. Its actual private-loopback HTTP tests
exercise the collector/protection refresh. Custom tag mappings are now validated,
detached and supported by the collector adapter. Worker settings must explicitly
supply them; no settings are silently read or changed here.

`sqlite_scheduled_paths` observes explicitly configured roots without a disposable
marker or filesystem-name policy and never mutates them. The actual executor
remains restricted to marked disposable roots. `sqlite_scheduled_pending_review`
never follows retained media paths or clears/replays an operation. It refuses
WAL/hot-journal snapshots rather than creating SQLite recovery sidecars.

These implementations do not wire the live worker or change JSON authority.
Native Tower acceptance and exact-implementation test CI have passed; Gate 6 is closed.
Production multi-library routing/settings/credentials and release activation stay
in Gates 8–10. The former host-wide maintenance fence is not required by this
scheduled operating model.


## Gate 6 closure

On 2026-10-24 the operator supplied the required Tower result: all 27 disposable
filesystem/integration tests and 11 HTTP transport tests passed, with final status
`scheduled_gate6_acceptance_complete`. Together with passing implementation CI,
this closes Gate 6 for the scheduled model. Historical intermediate progress
statements above do not override this closure. Gate 7 remains a separate
reconciliation milestone. JSON remains authoritative; no production behavior,
backend selection, image deployment or deletion setting changed with closure.


## Manual read-only preview exception

An explicit administrator-requested preview scan may collect outside the daily
slot in the separately bound scheduled-preview release. This is not a manual
media-action permit. It shares the regular cooperating run locks, cannot move
media, deliver Arr updates or checkpoint lifecycle clocks, and does not consume
or bypass the durable daily claim. Live action scheduling and at-most-once daily
attempt requirements above remain unchanged. The UI calls this Run Preview Now.
