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
- Final production bindings and the activation-capable release image: pending.
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

Preserve the observed `DRY_RUN=true` policy for initial deployment. The current
candidate `_configured_run_inputs` rejects that value: its disposable rename
acceptance path requires explicit false. This refusal must not be bypassed by
flipping production settings or simply deleting the check.

Before activation, implement and test a genuine scheduled preview path. It must
complete fresh collection and report the capped proposed actions without media
rename, Arr PUT, move intent creation or lifecycle clock advancement. Discovery
clock proposals must remain advisory in that preview; failures must not appear as
a successful empty run. Daily claims and process history must accurately identify
preview attempts, and history must not report completed moves. Existing live
rename acceptance stays explicit and separately tested. This is implementation
work still outstanding, in addition to the sealed activation boundary and live
backup/migration/rollback tooling.
