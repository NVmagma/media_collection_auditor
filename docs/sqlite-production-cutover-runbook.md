# Scheduled SQLite preview production cutover — approval package

**Status: approved scheduled-preview deployment completed and live-verified; Gate 10 closed for this scope.**
The final accepted image, packet, controller and live evidence are recorded in
[Gate 10 final acceptance](sqlite-gate10-release.md#final-publication-tower-cutover-and-live-verification).
The earlier image/packet selection below is historical; use final acceptance
identities for recovery. Do not rerun deployment against the occupied control root.
The sealed candidate remains sealed. A separately accepted immutable worker image
supports scheduled preview only. Production auditor settings/template and tracking authority changed in the approved
cutover. Media remains unchanged and read-only. Earlier Tower registry pushes
were denied before any service changes. Historical sections below record earlier steps;
the exact initial release selection and launcher procedure follow here.

## Exact initial preview selection

- Private packet: `/mnt/user/sql_test/cutover-review.sSK5fF`.
- Worker: `sha256:83933b4aa1819ec156f8432f6ac64c234a21a32123de8655c893dd797c8c2db8`;
  app revision `54372f8b476b8affcb7b51e705bfc5cdbcb39381`.
- Selection fingerprint:
  `63613834a4f2e1506fea627be836599dd3cde75182bf8d79a4d0416bd1c438d4`.
- Original container: `b637b8526244f54852a9a7f22279311e4aa8d7d5a982d701d82234e36d6cca88`.
  Its immutable image/configuration are pinned through the private packet.
- Movies only, 02:00 America/Los_Angeles, dry-run preview, cap 10; media/root
  filesystem read-only. No moves, deletion, pruning, Arr delivery or lifecycle
  clock advancement is possible in this worker profile. Tracking/coordinator
  observations remain advisory. Port 8089 and all 53 application environment
  entries are preserved. Saved settings are frozen until reviewed rebinding.
- New root-owned 0700 control directory:
  `/mnt/user/appdata/media_collection_auditor_sqlite_control`.
  Existing appdata ownership/permissions remain unchanged.

The fingerprint pins all six captured private input hashes, original/preview IDs,
worker revision, proposed XML hash, repository and schedule/port/library/control
selection. The request verifier also reconstructs private outputs and effective
policy. A fingerprint is a selection check, not consent to execute a deployment.

## Host launcher procedure

`scripts/sqlite_preview_service_host.sh` takes an explicit mode, exact worker ID,
private packet, fingerprint and tested controller commit. The working checkout
must be `feature/sqlite` at that commit with committed runtime/controller inputs;
its app tree must match the accepted worker's app tree. Use the full controller
commit from the passing acceptance workflow and final approved command, not a
moving branch name. No worker rebuild is needed for script-only integration.

`review` only verifies the private selection through a new network-isolated
read-only helper. It does not publish, create the control directory, mount a
Docker socket, access the real template directory or control production services.

After explicit human approval, `deploy` performs this fixed sequence:

1. Verify private inputs and the exact fingerprint. Refuse remote Docker
   contexts, a changed worker/app tree or any occupied control destination.
2. Tag and push only the accepted local image to
   `ghcr.io/nvmagma/media_collection_auditor:sqlite-preview-54372f8b476b-83933b4aa1819ec156f8432f6ac64c234a21a32123de8655c893dd797c8c2db8`.
   It does not move `latest`, `feature-sqlite` or another existing release tag.
   Missing registry write credentials fail here before service changes.
3. Resolve an immutable digest under the same repository and require that local
   inspection of that digest returns the exact accepted image ID. The service
   client repeats image/revision/digest verification before its first stop.
4. Exclusively create the new private control root and start the reviewed
   transient controller. It validates current original container/config/mount
   identity and current settings/template bytes before service handoff.
5. Stop only the auditor; back up fresh stopped-writer JSON and byte-exact saved
   settings; prepare parity-verified revision-zero SQL; stage settings and bind
   the frozen preview. JSON tracking is never overwritten with an old snapshot.
6. Rename/retain the original, create/start the preview, require authenticated
   preview APIs and unauthenticated 401 responses, then atomically replace only
   its captured managed Unraid template with the verified digest-bound proposal.
   Each external intent is durably journaled first. No automatic retry or rollback.

The controller binds its own private packet/control root, existing auditor logs,
read-only media, Docker socket and the Unraid template directory. Code reads/writes
only `my-media_collection_auditor.xml` there. DAC_OVERRIDE lets its root process
stage settings under the existing 99:100-owned logs directory without chmod/chown
of that directory. CHOWN is not granted to the production controller. Docker
socket access is a control capability; the code enforces exact selected IDs and
never stops the daemon, NFS, SMB, mover, other containers or web management.

The original container is retained as
`media_collection_auditor_rollback_b637b8526244`, stopped with its original
restart=no configuration. Do not manually reconfigure/start either auditor or
Apply its Unraid template during the transaction. The approved maintenance
protocol trusts host administrators to follow this rule.

## Explicit recovery

Use `rollback` with the same worker ID, packet and selection fingerprint and a
tested controller revision. It reads the retained immutable reference; it never
tags or publishes. The controller stops the recorded preview, verifies current
revision-zero SQL parity with retained JSON and absence of pending operations,
restores exact saved settings/template bytes, archives/retains the stopped
preview, then restores the original name and starts the original container.
No container, image or SQL evidence is removed. A lost create acknowledgement
requires an explicitly reviewed full preview ID as a sixth launcher argument;
the controller never adopts an arbitrary container by name.

On any failure retain the packet/control artifacts and terminal status. There is
no automatic restoration. Changed settings/template, a corrupt/incomplete journal,
advanced/mutated SQL or changed source identity blocks replay/recovery for review.
Advanced state requires the existing current-state export/inspection procedure;
never restart JSON from an older tracking backup. After successful deployment,
verify live summary/audit-status API results and the expected next daily slot
before closing Gate 10. API `production_activation=preview_only` is expected;
`production_authorized=false` means media operations remain unauthorized.

## Acceptance of this package

Tower passed the 23 service contract cases and actual scoped Docker/API handoff/
recovery at controller `e3207f94d7ee360bce6fab16b6200872bae9695d` using the exact
accepted worker above. Its disposable original was an idle stand-in; real old
image JSON compatibility was separately verified earlier. The host launcher's
publication/failure order is covered by command-shim tests with no Docker socket
or real `/mnt` writes; CI also exercises the actual `review` launcher against a
new synthetic packet. Registry publication and production deploy/rollback remain
unexecuted until the explicit final approval.

## Historical development evidence (superseded by the approval package above)

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

Tower rejected the original `/proc/<pid>/fd/<fd>` Docker bind source before the
renderer started. The renderer now receives an ordinary canonical host path;
its device/inode must match the held host descriptor before any input read or
output write. Host capture still uses the descriptor. The shell checks path
identity before and after the helper. CI exercises this exact Bash bind/CLI
handoff against a new synthetic host-backed packet with the real preview image,
and unit tests reject substituted mount identities before reading credentials.
Failed review packets are retained privately and never reused; retry creates a
new packet. The failed helper mount did not change the running auditor.

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


## GitHub Actions publication instead of Tower push

The user approved publishing through Actions to avoid Tower package-write tokens.
Manually dispatch `sqlite-candidate.yml` on `feature/sqlite` with
`publish_preview=true`. Automatic push runs and default manual runs do not publish.
The workflow runs the full acceptance sequence first, then tags and pushes the
same tested preview image without rebuilding, using its job-scoped GITHUB_TOKEN.
It publishes a versioned tag only, never latest or feature-sqlite. The public
`preview-publication.json` artifact records image ID, source revision and immutable
repository digest; it contains no private packet or credentials.

Pull that exact digest on Tower. A CI rebuild has a new image identity and source
revision, so capture a NEW private review packet for it with the existing read-only
capture script. Do not reuse the earlier packet's fingerprint. After reviewing the
new packet, invoke the tested controller with:

`deploy-published IMAGE_ID PRIVATE_PACKET NEW_FINGERPRINT CONTROLLER_REVISION PUBLISHED_DIGEST`

This mode requires the same repository's immutable digest and verifies that its
cached image ID exactly matches the newly reviewed selection before creating any
control directory or stopping services. It does not tag, push or pull. The original
cutover/recovery transaction is unchanged. Updating the image field alone is not
the first SQLite migration procedure. Prior production approval persists for this
same Movies-only, read-only 02:00 Pacific preview scope.


## Post-cutover recreation incident and clean reinstall

The operator removed the pinned image digest and later restored it through Unraid.
The recreated container then lacked `/sqlite-control`, had writable `/media`, and
had lost the read-only root setting. Preview correctly refused startup. After
manual mount/environment repair, the read-only diagnostic failed opening the
saved config in `_effective` before SQLite validation. Current mounts and config
path have not yet been verified, so missing/changed SQLite data is not established.
The prior live verification is historical; current frontend/API availability is
not confirmed. Rebuilding an image does not repair missing binds or saved files.

The operator requested all commits pushed and a fresh Actions-built runtime for a
clean reinstall, explicitly selecting a fresh SQLite preview rather than a JSON
baseline. Preserve old appdata, SQL control files, private review packets and the
stopped original rollback container. Use separate new appdata/control directories
for the clean preview, with explicit initialization and binding before startup;
publishing an image alone does not create that binding. The installer must not
reuse the original cutover transaction against the changed container identity.

Carry forward the reviewed Movies-only 02:00 America/Los_Angeles preview settings,
read-only media, port 8089 and disabled media operations. New tracking starts
empty by operator request; the old tracking is retained separately. A fresh
preview scan reports advisory observations and does not authorize media moves.
Fresh preparation, actual startup validation and the exact published image are
required before recommending the replacement container.


Fresh preparation uses `scripts/sqlite_preview_fresh_prepare.sh` with the published
preview digest, prior packet and fingerprint, and existing appdata parent. It
creates a randomly named NEW root with separate private logs/control children,
checks the prior packet inputs and reconstructed settings, writes an empty JSON
seed only in the new logs, and uses the existing offline parity/binding procedure
to produce a revision-zero SQL preview. It preserves connection/integration
credentials privately in `runtime.env` and generates a digest-bound
`fresh-template.xml`. Neither file should be pasted into diagnostics.

The helper has no Docker socket and no external network; old packet and media
are read-only. It does not alter the old appdata, control state, template or any
service. Occupied/partial outputs are retained and refused, never overwritten.
The workflow exercises eight fresh-fixture cases, including actual preview web
login page and authenticated/unauthenticated API readiness, before publication.
Starting the new container and installing its template use only this new root;
those operator actions follow successful preparation and review of redacted output.


### Fresh Tower runtime verified (2026-10-26)

Implementation `12f0ba4d8952366f5c90b990ad2bbc79defac819` was published by
[Actions run 40270775704](https://github.com/NVmagma/media_collection_auditor/actions/runs/40270775704)
after 3,333 tests, 82 subtests, and 8 fresh-start fixture cases passed. The first
fresh fixture run found Docker's requirement for rslave/rshared propagation for
binds inside its own daemon storage; the fixture was corrected and actual local
and CI web/API startup passed. Production mount behavior was not changed.

Published reference:
`ghcr.io/nvmagma/media_collection_auditor@sha256:6d22760eb22ca6d655216142ac31dcf647a9c5d03e077dded584732282d3acff`.
New private root: `/mnt/user/appdata/media_collection_auditor_fresh.bXSlJM`,
with `logs` and `control` children. The operator completed preparation, then
started `media_collection_auditor` as container
`b238b53e9f824f8b1e988364f5f80a550a77b0db1f10c71c19d1d596df155baf`.
Reported mounts were read-only media and writable new logs/control. Both live
summary/audit-status APIs returned HTTP 200, SQLite/preview_only/scheduled_preview,
read_only=true, media_actions_authorized=false. All five tracking counts are zero,
as intended for the clean database. Next run is `2026-10-27T09:00:00+00:00`,
October 27 at 02:00 America/Los_Angeles. No future scheduled scan completion or
browser/frontend observation is implied by this API result.

The old data was not imported or removed. The command retained any existing
stopped failed primary under `media_collection_auditor_before_fresh_<id-prefix>`.
Do not start that retained container or the original rollback concurrently.
The operator subsequently reported `status=fresh_unraid_template_installed`.
The installation command validated the pinned digest, read-only media, fresh logs/
control paths, read-only root parameter and all template environment entries
against the running container before retaining the previous template and
replacing `my-media_collection_auditor.xml`. No restart occurred. Close stale
Unraid edit tabs before opening the persisted template. A subsequent DockerMan
recreation has not been tested on Tower; template persistence alone is not that
acceptance claim. Existing saved configuration
and policy are frozen by the preview binding. The original service journal belongs
to the first deployment and is not a recovery journal for this fresh instance.


### Dashboard shortcuts, title links and retained tracking restoration

The running fresh container lacked the `net.unraid.docker.webui` Docker label;
a persisted XML WebUI field alone does not add it to an existing container.
The preview recipe and service payload now supply the root WebUI label, and the
rendered Unraid template includes the matching label for later recreations.
The root route already redirects anonymous visitors to `/login`; actual-image
acceptance now verifies that redirect. Dashboard table/poster titles link through
the authenticated Jellyfin route; its display-title/year fallback regex is fixed.

After observing empty Homarr lists, the operator explicitly chose to restore
previous tracking records and clocks. `sqlite_preview_fresh_prepare.sh` accepts
an optional fifth argument `restore-previous`. It validates the prior private
packet and the retained source digest, imports that entire snapshot (including
extensions and TV-prefixed records) into NEW private files, and uses the existing
parity/binding preparation. It does not overwrite either old deployment, invent
missing timestamps, enable TV moves, or write media. The redacted result includes
counts split by library to establish whether prior TV holding records exist.
The corrected image and restored preview need fresh startup verification and
matching template installation before reporting this follow-up complete.


### Restored-records UI/TV release installed (2026-10-26)

[Actions run 40314107390](https://github.com/NVmagma/media_collection_auditor/actions/runs/40314107390)
accepted `b846e88af752dcfb9cb42c52acef0c85df2574fe` with 3,342 tests, 82 subtests
and 9 fresh/restored startup cases, then published:
`ghcr.io/nvmagma/media_collection_auditor@sha256:b602ae33bcf83b231b4e697254ce28e5fb8b4dec0e6442f00c66f8cf10f6e64c`.
Image ID: `sha256:fea2f73da21afde0cb463eb1208464744417b5d0a7d5fdd5970ec7a0dd675722`.

The operator prepared `/mnt/user/appdata/media_collection_auditor_fresh.nFGzhm`
using `restore-previous`, preserving all retained clocks. Counts: Movies waiting
454, Holding 4, Keep 13; TV waiting 68, Holding 0; Removal and Arr pending 0.
The current primary was retained before the replacement; the operator confirmed
the new immutable reference running, then confirmed the TV widget worked after
Homarr query parameters moved from its Path into `query: {"library":"TV"}`.
The widget correctly showed no TV Holding records. The request examples were
corrected at `87e9e11`; 28 title/example tests passed locally, and this correction
requires no image change. Tracking Holding entries, rather than tags alone, drive
leaving-soon lists; the preview still does not execute lifecycle moves.

The operator subsequently reported `status=restored_unraid_template_installed`.
The command checked the digest-bound template, fresh nFGzhm logs/control mounts,
read-only media, WebUI label and all environment entries against the running
container, retained the prior template, then replaced the managed template
without restart. Old data and retained containers remain preserved. Close stale
Unraid edit tabs before using the updated template. Actual subsequent DockerMan
recreation and browser click-through results have not been independently reported;
they are not implied by the successful API/widget and template checks.
