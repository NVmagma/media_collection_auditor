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
