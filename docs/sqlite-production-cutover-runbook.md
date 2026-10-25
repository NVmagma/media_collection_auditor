# Scheduled SQLite production cutover — review draft

**Status: not authorized and not executable as a live cutover.** Gate 10 remains
open. The current candidate image intentionally refuses SQLite activation. No
container, share, service, source state, setting or production tag has changed.

## Accepted and outstanding evidence

- Scheduled lifecycle/Arr/protection/tracking authority and whole-show TV scope:
  Gates 1–9 accepted. Pruning, permanent deletion and cross-filesystem moves stay
  disabled. The accepted operating model does not require host-wide NFS/Docker
  shutdown; it retains the documented concurrent-media-writer limits.
- Candidate JSON entrypoint/API and packaged scheduled runtime: accepted on Tower.
- Current-source full-suite/image/host-backed CI: run 40153655744, 3,160 tests and
  53 subtests; immutable base/runtime dependencies are pinned.
- Disposable advanced restore on Tower's actual shfs and native directories:
  accepted at `44c1c84` (17 cases on each filesystem), including retained success/
  interruption evidence and the staging-descriptor repair.
- Production bindings are recorded below; the activation-capable release image
  remains pending.
  The existing sealed candidate cannot be made live by changing an environment
  variable. Activation implementation, final tests and approval are distinct
  remaining work, not implied by this draft or a successful lab.

## Required production binding packet

Refresh these observations immediately before preparing the final release. Do
not assume that historical container configuration remains current:

| Binding | Required evidence |
| --- | --- |
| Auditor container | Exact name, running state, immutable current image ID/digest and restart policy |
| Persisted state | Effective `STATE_FILE` and host/container mount mapping; canonical regular file identity; quiescent snapshot hash |
| Saved settings | Effective saved-config/environment precedence; explicit daily HH:MM and IANA zone; enabled libraries and action cap |
| Safety policy | Permanent/filesystem deletion, season pruning and cross-filesystem moves disabled; initial dry-run policy explicit |
| SQLite control | Dedicated durable control directory and state.db, disjoint from all media roots; writable by intended container UID; no aliasing |
| Media routing | All enabled stage roots, application path aliases and supported atomic no-overwrite move capability |
| Recovery | Retained original JSON backup and immutable rollback image; current-state JSON export path and pending-operation checks |

Do not collect/paste tokens, full environment dumps or title inventories for this
packet. A read-only observation is not authorization to stop or recreate services.

## Proposed controlled sequence

1. Review the final immutable activation-capable release and binding packet.
   Obtain explicit approval for the concrete update/cutover after all checks pass.
2. Quiesce the auditor state writer for the cutover and prevent a second auditor,
   manual rescue, migration or administrator state edit. Media-service shutdown
   is not a blanket prerequisite under the accepted scheduled model. Preserve
   existing container configuration, image identity and restart policy privately.
3. Validate and back up the now-stable JSON source without overwriting it or any
   existing backup. Record exact source/backup identities and hashes. Any source
   change, unreadable file or unresolved operation blocks the cutover.
4. Migrate to a new dedicated SQLite database, preserving all clocks, library
   prefixes, Arr metadata and unknown fields. Verify full parity and persistence.
   Never initialize empty state as a fallback or overwrite an existing database.
5. Start only the reviewed release with its approved backend/configuration. A
   restart or early/manual wake must wait for a future daily slot. Verify selected
   dashboard/Homarr authority, unavailable-state behavior, authentication, next
   schedule and durable control binding before any scheduled attempt.
6. Observe the first bounded scheduled run. On failure or uncertainty, stop
   additional dispatch and inspect retained claims/intents. Never clear these
   artifacts, replay a move/Arr request, or restore an earlier JSON backup merely
   to make the worker start.

These steps are a review sequence, not commands to execute now. Live state
migration/publication and activation tooling must be finalized and tested before
approval; the current restore helper accepts only new private files in marked labs.

## Rollback decision rules

- **Before SQLite has advanced:** with the state writer quiescent, verify the
  source still matches the retained original backup and no uncertain operation
  exists. Reuse the preserved JSON authority only after exact parity review.
- **After SQLite has advanced:** the original backup is historical. Export and
  verify the latest SQLite snapshot, including all Arr/unknown tracking fields.
  Publish a new private JSON candidate without overwriting existing history;
  verify fresh JSON load/save/restart before reviewing any authority switch.
- **Pending intent, partial restore or uncertain acknowledgement:** retain the
  database, journal, candidate, staging and published output as found. No automatic
  cleanup, retry, clearance or fallback is allowed. File presence alone does not
  establish a successful restore or permission to start a worker.
- **Failed migration or incomplete backup:** leave the original source and all
  artifacts intact; do not select SQLite or create empty tracking state.

Rollback cannot undo already completed media/Arr actions. Matching restored
tracking must describe those completed actions rather than rewind their clocks.
Current-process coordinator history is advisory and is never a substitute for
the durable tracking snapshot, daily claims or operation intents.

## Tower binding observation — 2026-10-25

The read-only preflight observed the following current deployment inputs. These
are planning bindings, not a quiescent backup or activation permission:

- Container `media_collection_auditor` running, restart policy `no`. Follow-up
  inspect supplied rollback reference
  `ghcr.io/nvmagma/media_collection_auditor@sha256:4575aa35c0998aec937f1145b19c685af50d83fb00829f99be0a1a2017997db4`
  and local image ID
  `sha256:c33a4aedd8531234bb2d5bd67e5c81657e2a9a313852c970da9e5d1f9969a85b`.
  Preserve both: the registry digest and local image ID identify different
  image objects and are not expected to match. Recheck before cutover.
- `/mnt/user/media_storage` maps writable to `/media`;
  `/mnt/user/appdata/media_collection_auditor` maps writable to `/app/logs`.
- Movies enabled, TV disabled. Movie stage roots are `/media/Movies`,
  `/media/Movies_hold`, `/media/Movies_keep`, `/media/Movies_removal`.
  All were observed on device 47 (shfs); matching device numbers alone do not
  prove atomic no-overwrite rename support for an eventual production move.
- JSON authority, `DRY_RUN=true`, action cap 10, movie waiting 30 days,
  Holding 7 days, Removal 7 days, favorites enabled. Permanent/filesystem
  deletion, cross-filesystem moves and season pruning are disabled.
- `/app/logs/auditor_state.json`: 33,532 bytes; observed counts first_seen 522,
  queued 4, keep_seen 13, in_removal 0, arr_sync_pending 0; no pending-operation
  key observed. Hash `da683968d5945e3e26aba2fae40aaa317a5f0cf97eba96847124220dce208bb5`
  is historical metadata only; a final quiescent capture must be revalidated.
- Probe ran as UID/GID 0. Proposed `/app/logs/sqlite_worker` was unavailable or
  aliased; do not assume it exists, create it implicitly, or adopt an existing
  database. The eventual new control directory belongs beneath the persisted
  appdata mapping and must pass identity/disjointness checks.
- Daily time and zone were blank in the observation. The user subsequently
  selected `02:00 America/Los_Angeles`, with initial dry-run retained. These are
  approved deployment inputs, not settings already written to Tower. Schedule
  handling must use the existing daily-slot rules across daylight saving changes,
  with no immediate startup/catch-up dispatch.

### Dry-run release requirement

Preserve the observed `DRY_RUN=true` policy for initial deployment. At preflight,
the candidate rejected that value because its disposable rename acceptance path
required explicit false. The new preview branch resolves this without changing
production settings or relaxing the disposable rename entry point.

The candidate now implements a scheduled preview path, covered by private HTTP
fixtures and packaged-image/host-backed CI. Tower acceptance is pending. It must
complete fresh collection and report the capped proposed actions without media
rename, Arr PUT, move intent creation or lifecycle clock advancement. Discovery
clock proposals must remain advisory in that preview; failures must not appear as
a successful empty run. Daily claims and process history must accurately identify
preview attempts, and history must not report completed moves. Existing live
rename acceptance stays explicit and separately tested. Tower preview acceptance
is still outstanding, in addition to the sealed activation boundary and live
backup/migration/rollback tooling.

## Preparation tooling boundary

The candidate now includes `app.sqlite_release_preparation` as the offline
backup/migration preparation CLI. It accepts only a source path, new control
directory and expected source hash; it has no backend/service activation option.
A new durable request/byte-exact backup/revision-zero database/receipt are created
while the original JSON is preserved. Any interrupted or completed directory
refuses reuse. This implementation still needs actual Tower filesystem acceptance
and final integration/review before live execution is approved.

Scheduled preview acceptance has passed on both Tower filesystem paths at
`5599aad`; the accepted initial schedule and rollback image remain as recorded.
The production selection gate remains sealed. Latest SQLite export/recovery
binding and activation-capable release review are still separate outstanding work.

## Latest-state recovery tooling boundary

The candidate now includes `app.sqlite_release_recovery` with explicit export and
inspection actions. It requires a successful preparation receipt bound to the
same database inode, a preserved original JSON/backup, current private control
identity, and the cooperating source/worker locks. It exports the current advanced
snapshot into a new candidate/request/completion triplet, without overwriting
original JSON or switching a backend. Incomplete or stale candidates and pending
operations block recovery; an old backup is never substituted automatically.

The final authority-switch package must run current-candidate inspection again
with every auditor writer stopped before selecting any new JSON `STATE_FILE`.
A prior matching report is not a permit: a later SQLite revision invalidates it.
The production activation gate remains sealed; running this CLI on live state
still awaits the final concrete cutover/recovery review and approval. The new
recovery body has only been exercised against disposable inputs so far.

## Initial preview release and control mount

The first activation-capable image is a separate immutable
`scheduled-preview-v1` build, not an environment switch in the sealed candidate.
It requires a bound prepared revision-zero snapshot and frozen saved/env policy,
serves SQLite tracking/coordinator observations, and only previews due daily
runs. It cannot run live moves or Arr delivery, checkpoint lifecycle clocks,
prune seasons or delete media. Changing saved settings blocks execution until
reviewed offline rebinding; ordinary configuration edits never grant capability.

Tower's directory observation confirms process UID/GID 0:0 and `/app/logs` owned
99:100 (0755). Preserve that existing directory and its permissions. Plan a new
root-owned 0700 host directory
`/mnt/user/appdata/media_collection_auditor_sqlite_control`, mounted separately at
`/sqlite-control`, with `SQLITE_STATE_FILE=/sqlite-control/release/state.db`.
Use exclusive creation and refuse any occupied destination. Existing original
JSON/config stay under `/app/logs`; the initial media bind can be read-only.
No such production directory, mount or setting has been created or changed.

Preview implementation and both image recipes pass CI 40207027548 (3,246 tests,
61 subtests), including actual-process API/future-schedule/refusal/shutdown checks.
Actual Tower preview-image acceptance passed on both filesystem paths at
`5dbb1d87a238742ec2597d0e057b6bde78953684`, image
`sha256:108db5f6e13a1a1af273504feeb0af131a5129c8d32017e4331cb0eb9b7bd170`:
16 cases per path plus actual process/API/future-slot/shutdown checks.
Before asking for final
production approval, complete the private existing-container configuration/rollback
capture, settings backup/schedule update, source-writer quiescence, fresh migration
hash, new private mount preparation, exact approved image publication/selection,
and post-start API/next-slot/rollback commands. Never print/paste the private full
container configuration or env file; they contain credentials. Existing services
outside the auditor are not part of this cutover.

## Private current-container review packet

`scripts/sqlite_preview_cutover_review.sh` captures the expected running auditor's
Docker metadata, saved settings and a stable JSON observation into a new private
0700 directory. It reads those files through the existing Python interpreter
without importing the worker, changing settings, or acquiring a writer permit.
The observation is explicitly not a quiescent migration source. The packet
contains credentials: retain it on Tower and paste only the redacted terminal
summary. Its held directory descriptor anchors new writes during capture.

The offline renderer preserves application environment/settings and published
ports, proposes the approved 02:00 America/Los_Angeles schedule, a separate private
control bind and read-only media/root filesystem. Unsupported current layouts
block for review. Exact-ID stop/archive/create/rollback argument lists are data,
not executed commands; the private env-file placeholder is intentionally not an
executable deployment instruction. Existing Unraid XML, when present, is captured
privately for a later managed-template update. Partial packets refuse reuse.

The script also launches a new isolated container from the exact cached rollback
image and tests synthetic JSON load/save parity in private tmpfs. It has no media
binds, production configuration, network or published ports. This does not prove
that production state is quiescent or authorize restoring an old snapshot.

Final installation/controller integration, fresh stopped-writer preparation,
managed-template changes, immutable registry selection and explicit production
approval remain outstanding. No production services or settings change during
this review step; Gate 10 is still open.
