# Initial SQLite live moves

Requested 2026-10-28. The current production image remains scheduled preview.
This work does not enable production moves by changing an environment variable.

## First release scope

Run the existing complete-scan → bounded plan → fresh per-title protection check
→ atomic no-replace rename → guarded SQLite completion path at the configured
daily time. Keep whole-show TV behavior, all-user favorites and title tags. Start
acceptance with one global action across Movies and TV, then review a larger cap
after a successful production canary. Manual requests remain read-only scans.

Permanent/filesystem deletion, cross-filesystem copy/delete, TV season pruning,
NFS/kernel/service fencing and automatic uncertain-operation replay are excluded.
Moving a title to Holding or Removal changes its location; this release will not
reclaim space by deleting it. Unavailable protection information blocks moves.
The scheduled model retains its documented external-writer race limitations.

## Work required before activation

1. **Policy and disposable worker acceptance:** explicit SQLite/non-dry-run
   values, explicit disabled destructive flags, one-title global cap, complete
   movie/TV scan, retained JSON unchanged and no duplicate daily dispatch. The
   new policy validator grants no execution authority and does not open the
   existing sealed or preview gate.
2. **Mutable-state live binding:** a distinct immutable live recipe/profile and
   explicitly prepared binding. Normal guarded SQLite revisions after successful
   moves must remain valid. Replacement/corruption, changed roots, unsafe flags,
   incomplete settings application and unresolved intents must block. Preserve
   status/UI access and report a paused worker honestly.
3. **Actual image acceptance:** run the public scheduled entrypoint against
   disposable media, verify protection failures and tag changes, Arr delivery,
   crash/restart and retained unresolved intent. Manual requests must never
   execute moves. No startup run, catch-up or uncertain replay.
4. **Controlled deployment:** preserve a current logical backup and tracking,
   verify same-filesystem rename support in disposable tests on Tower, prepare
   an explicit live selection and template, and keep permanent deletion disabled.
   A rollback after moves must export the latest SQLite state; restoring the old
   pre-move snapshot would lose actual clocks and paths and is not acceptable.

## Current acceptance

`validate_initial_live_policy` validates a detached policy with no filesystem,
network or activation side effects. `sqlite_live_policy_lab.sh` exercises it with
actual disposable renamed directories, private synthetic HTTP responses, existing
SQLite state and the common scheduled worker internals. Production release gates
remain closed to live execution. The lab mounts no production media, appdata,
Docker socket or host port and uses no external API requests.

## Test placement and host-specific diagnostics

Routine policy, complete worker, failure and Docker wrapper acceptance runs in
GitHub Actions. The user upgraded Actions capacity; Tower should be used only
for host-specific capability/deployment checks that CI cannot establish.

The first user-share Tower run returned zero completed moves; the original
assertion did not include the worker's stop reason, so the cause remains unknown.
Zero completed moves does not prove no rename occurred: an uncertain post-rename
outcome must also remain blocked. The fixture now includes only fixed worker
status/reason, error type, operation category and numeric errno in failure output;
it never prints exception text, titles, source paths or HTTP credentials. An
unsupported-rename regression verifies retained intent, unchanged source and no
fallback. The same host-backed Docker lab is now an explicit candidate CI step.
No production activation or safeguard relaxation is implied by this diagnostic
change. A host-specific failure must be resolved before production live moves.

The failed `5d5605f` run was at `/mnt/user/sql_test/live-policy.ob6E1c`.
Its unittest temporary media/state are cleaned after failure, so a retrospective
filesystem/state diagnosis cannot be reconstructed from that directory. For a
host-specific reproduction, the optional `move-only` lab argument runs just the
single capped-move case and omits other policy and transport cases. Failure output
includes a fixed allowlisted guard code, errno, disposable source/destination
presence and unresolved-intent presence. Routine complete acceptance stays in CI.

## Confirmed Tower user-share blocker

The targeted `cec665a` run at `/mnt/user/sql_test/live-policy.TsDS5F`
reported `atomic_rename_unsupported`, errno 22 (`EINVAL`), from the atomic rename
call. The disposable source remained present, the destination was absent, and
the pending intent was retained. This is a failed filesystem-capability check,
not a reason to relax no-overwrite semantics or clear an uncertain intent.
The production container and media were not touched.

Initial live activation cannot use the tested user-share path with this move
primitive. Next inspect the native disk/pool locations behind `media_storage`.
A native-root deployment may be possible if complete stage contents are on one
verified filesystem. Do not replace the container mount based solely on finding
one native directory: a user share can span multiple devices, and a partial view
must never be mistaken for complete inventory. Cross-filesystem copy/delete and
unsafe rename fallback remain excluded. No kernel/module/NFS changes are needed
for this inventory. Only a small disposable same-filesystem capability test will
be needed on Tower after selecting a valid native-root layout; routine testing
continues in CI.

## Native media view candidate

Tower's read-only stage inventory found `/mnt/media/media_storage` on Btrfs
(`/dev/sdb1`), with counts matching the user share in all eight stages: Movies
514/4/13/0 and TV 70/0/0/0. These observations identify a candidate, not a complete
mount migration or future placement guarantee.

`sqlite_media_view_review_host.sh IMAGE SHARED NATIVE` mounts both views read-only
and reports only per-stage counts and whether relative directory/file names and
file sizes match. It does not read media contents or print titles. It refuses
symlinks/special entries, missing stages, unstable repeated observations and
resource exhaustion. Matching metadata is not proof of byte equality or writer
exclusion. The actual wrapper runs in CI with synthetic views; unit tests cover
mismatched names with equal counts, missing nested media and concurrent changes.

Before changing the production bind, require matching view metadata, native
same-filesystem disposable rename acceptance and review of the share's primary,
secondary and mover placement policy. Keep application-visible `/media` paths
and Arr/Jellyfin path mapping stable if a complete native bind is selected.
Do not exclude content on another backing device or treat the snapshot as a
permanent promise that mover will not relocate future content.

## Tower native acceptance and mutable-binding implementation

Tower's `9335352` review matched all relative directory/file names and sizes in
all stages: Movies 6,641 entries/514 titles, Holding 58/4, Keep 170/13, Removal
empty; TV 10,278/70 with the other TV stages empty. Native stages were observed
on one mount/device. Share settings were `shareUseCache="only"`,
`shareCachePool="media"`, `shareCachePool2=""`, with empty include/exclude lists.
The single move-only case passed on `/mnt/media/sql_test/live-policy.Yut5u6`.
No production bind, settings or media were changed. Routine tests continue in CI;
this resolves the identified native-path capability acceptance, not live release
activation.

The offline `sqlite_live_binding` implementation requires a distinct immutable
`scheduled-live-moves-v1` profile; default and preview profiles refuse it. It
requires new prepared state, exact source/settings/root identities, one observed
stage mount/device and an initial one-title global cap. Existing preview bindings
cannot be rebound in place. A durable request precedes integrity initialization;
completion follows verification. Partial preparation is retained without replay.
The public production activation gate is still unchanged.

Live integrity is explicit opt-in metadata. Guarded commits update the state
revision and digest in the same transaction; readers use a coherent read
transaction and validate the record when present. Legacy/preview databases do
not acquire this metadata during normal reads/writes. The live binding requires
its presence, allows valid later revisions and rejects pending intent for
execution while permitting read-only binding observation. Replacement roots or
databases, changed source/settings, missing integrity and partial settings
application are refused. These digests catch inconsistent state/metadata, not
malicious privileged rewriting of both. They do not provide an independent
rollback-proof history; live recovery must use the latest verified state.

Focused acceptance covers ordinary revision advances, raw state/revision changes,
transaction rollback, actual capped rename with its clock/integrity checkpoints,
and an uncertain actual rename retaining its intent and blocking further
execution. Still required: public live recipe/entrypoint, status/settings behavior,
actual-image crash/restart acceptance and the separate controlled live cutover.

### Read authority and execution authority

The compiled live profile now selects a separate binding gate. Read-only tracking
access accepts a valid database with a retained move intent so recovery information
can remain observable; execution rejects that same intent. Both paths redact
validation failures and revalidate bound tracking projections after capture.
Sealed and preview images retain their existing restrictions. No live image or
production cutover is provided by this gate change alone.

### Packaged live runtime acceptance

A separate `docker/sqlite-live-release.Dockerfile` now selects the immutable live
profile. Its daily worker revalidates policy after acquiring the shared locks and
validates advanced tracking before recording completion. Manual moves remain
unavailable. During the initial one-action canary, settings are displayed but
cannot be saved through the legacy configuration route; reviewed preparation is
required. The deployed preview retains Apply Requested Settings.

The actual-image lab exercises one capped move with private Arr delivery, changed
protection, lost Arr acknowledgement, SIGKILL after rename, and the real web/API
entrypoint with a retained intent. All files and HTTP services are disposable.
Passing this lab is not a production cutover or authorization to change Tower.

The candidate workflow can explicitly publish the accepted live image using
`publish_live=true`. It publishes only a separate versioned `sqlite-live-canary-`
tag and reports its digest after the complete acceptance job succeeds. It does
not update `latest`, the preview tag, Unraid templates, or production services.
The published image still needs a newly prepared native-media binding before it
can run. Never replace the working preview image reference with the live digest
alone.

### Tower native acceptance — completed

Tower passed all five actual live-image scenarios at revision
`8b2d7198c00a6f8b672a379bf46fc4806165be07`: one capped move plus Arr delivery,
changed protection, lost Arr acknowledgement, SIGKILL after rename, and web/API
availability after restart with a retained intent. Only disposable native files
and a new container were used; production remains on preview.

### Backup-based live preparation

`scripts/unraid_live_prepare_host.sh` uses the already accepted live image and a
new verified logical preview backup. It mounts the explicitly selected native
media view read-only, creates fresh private logs/control directories, preserves
tracking and unknown fields, and retains the original preview configuration. The
only changed settings are DRY_RUN=false, the one-action global cap and the disabled
deletion/copy/pruning controls. Schedule, library selection and credentials remain
unchanged. No service payload is installed and no worker starts. Changed inputs
or interrupted preparations retain partial files and cannot replay. A fresh
backup is still an observation; cutover must check that it matches the stopped
original before starting the live worker.

### Read-only live cutover review

The live review builds a separate private proposed container/template from the
accepted registry digest. It preserves ports, credentials, UI metadata, restart
policy and the read-only container root. Only the explicitly reviewed native
media bind becomes writable in the proposal. The current template and container
are never changed by review.

Review verifies both current and prepared revision-zero tracking, retained source
and settings, preparation receipts, the new live binding and a fresh bounded
shared/native relative metadata comparison. It refuses stale inputs, duplicate
templates, unsafe policy, unexpected capabilities, changed private files and
nonstandard initial stage layout. Existing data mounts are read-only; only a new
private review directory is writable. Matching metadata does not claim byte
equality or exclusion of external writers. A reviewed proposal still requires a
separate tested service transaction and stopped-original freshness check before
activation.

### Approved minimal live filesystem capability

On 2026-10-29 the user explicitly approved preparation and testing of a root
canary with all capabilities dropped except DAC_OVERRIDE. Private SQLite controls
remain root-owned; Unraid media directories can remain 99:100-owned and 0755. No
production chmod/chown is required. Container root remains read-only, the global
action cap remains one, and permanent deletion/copy/pruning stay disabled. This
approval did not authorize starting the live service.

The proposal now enforces its own minimal capability rather than requiring an
older preview to already have the new policy. Template security, user and restart
flags are rebuilt to match the proposed Docker payload, so stale flags cannot
reappear on Unraid recreation. Policy validation uses effective saved settings,
while preserving runtime defaults and credentials. A disposable named-volume CI
case proves denial without DAC_OVERRIDE and atomic no-replace rename success
with that sole retained capability, preserving synthetic 99:100 ownership.

### Explicit live service handoff

`scripts/unraid_live_execute_host.sh` accepts `check`, `deploy`, or `recover`,
followed by the immutable reference, prepared root, private review directory,
backup packet, backup fingerprint, and native media root. Deploy/recover also
require the exact SHA256 of `review-complete.json`; an uncertain container create
requires its explicitly reviewed replacement ID for recovery.

Check revalidates the private review, backup, both database snapshots, binding,
source/settings identities, native/shared media metadata and managed template.
It mounts data and templates read-only and makes no service changes. Its Docker
socket permits engine access; a read-only bind is not an API authorization fence.

Deploy repeats the review after stopping the original, retains that container,
creates the exact reviewed payload, verifies the approved capability policy,
starts the daily canary and checks authenticated SQLite live API readiness before
installing the matching template. It never retries or automatically restores.
The first live release remains limited to one global action per daily run with
permanent deletion disabled.

Recovery is deliberately limited to unchanged initial tracking with no retained
intent. It rechecks before and after stopping the replacement. Any advanced
revision, changed snapshot or uncertain operation blocks stale-preview recovery;
latest-state recovery then needs separate review. Never start the retained old
preview over newer live tracking. All containers and journals are retained.

### Reviewed live settings application

The newer live source supports Apply Requested Settings using the same locked,
journaled configuration/binding transaction as preview. Live application accepts
advanced guarded SQLite revisions and preserves database bytes, clocks, Arr queue,
retained JSON, unknown settings and daily claims. An interrupted application keeps
scans paused and exposes explicit previous-settings restoration; it never retries
or restores automatically. Restoration refuses changed tracking or unknown file
identities. The web interface remains available for review and recovery.

The canary's DRY_RUN, maximum action count, deletion/copy/pruning controls, media
root and schedule time zone remain fixed. Time-zone changes require separate
claim-migration review. Ordinary connection, lifecycle, notification and library
settings use validated effective values and fresh media root checks; applying
settings does not request a scan. Source support is not a Tower update.

### Explicit manual live daily attempt

Run Live Scan Now uses the same full all-library collection, guarded clock
checkpoint, fresh protection reads, one-action cap, no-replace rename and Arr
completion as the timer. The administrator confirms using today's budget; the
same-origin POST requires exactly `{"consume_daily_slot": true}`. Read-only API
tokens cannot request it. This is a live run, not a preview, and permanent
deletion stays disabled.

Manual and scheduled attempts use the same retained zone/local-date claim. A
manual attempt before the daily time consumes that date; the timer does not run
again. A timer attempt prevents a later manual attempt. Failure, process death
and restart retain the claim, with no automatic replay. Pending operations still
block execution. A new daily time does not create a second claim on the same
date; the canary time zone stays fixed. Read-only previews retain their existing
separate behavior and do not spend live claims.

The public service reloads approved settings on wake; a wake alone does not grant
manual authority. Only a queued explicit live request reaches the manual path.

### Live-to-live backup preparation (2026-10-30)

`scripts/unraid_live_update_backup_host.sh EXISTING_PARENT` observes the running
live image through read-only inherited mounts and its own packaged live validator.
Only a new private `auditor-live-update-backup.*` packet is writable; no Docker
socket, host port or external network is exposed to the helper. The launcher
checks the selected image/profile, container identity and exact three bind mounts.

The separate live packet supports advanced SQLite revisions and retains all
logical tracking, extensions, Arr queue entries, saved settings and retained
source bytes. Every existing daily claim is captured as byte-exact base64,
including empty or interrupted claims. Unknown, linked or unsafe claim entries
block capture rather than being dropped. State/input/claim changes and identical
identity replacements prevent completion. Partial packets are retained without
replay or overwrite. The original SQLite database and claim directory are never
modified.

This is an observational backup, **not an update authorization**. A later live
candidate preparation must preserve these claims, and cutover must recheck the
latest state and claims after stopping the old worker. Do not use the frozen
preview backup/installer or change only the Docker image reference to update a
running live worker. Template capture records the unique managed XML; the later
proposal still needs to validate the complete recreation recipe.
