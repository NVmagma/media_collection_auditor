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
