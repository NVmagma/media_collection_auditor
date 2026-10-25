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
  still requires both `restore_acceptance_complete` results. An image-only
  restore test with `host_mounts=false` does not supply this evidence.
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
