# SQLite production move trust contract — blocked draft

This is the gate 6 acceptance contract, not approval to enable SQLite. The
production backend gate still requires JSON. The current executable runner is
restricted to marked disposable fixtures.

## Supported first execution model

The first proposed production model is one Linux mount, held source/destination
parent directories, and atomic no-replace directory rename. A held pre-rename
source descriptor must match the destination after the rename. Clocks and a
bound Arr queue entry can commit with intent clearance only after all required
in-process checks pass. There is no cross-filesystem copy/delete fallback.

The isolated implementation now additionally reads `mnt_id` from each held
parent/source descriptor's `/proc/self/fdinfo` record and captures the current
mount namespace identity. All three directories must have one mount ID and one
device. It rechecks the binding before intent and at execution boundaries.
Unavailable/ambiguous mount information fails closed before intent. A changed
binding after intent preserves the intent and stops further operations.
Linux documents this namespace-local descriptor field in
[proc_pid_fdinfo(5)](https://www.man7.org/linux/man-pages/man5/proc_pid_fdinfo.5.html).
Persisted mount IDs are diagnostic history only: they can be reused and do not
establish identity after restart or across containers.

Non-Linux hosts cannot perform the no-replace rename and remain non-execution
test environments. The mount check applies to Linux descriptor-bound execution;
legacy disposable helpers retain their existing test behavior. Nothing bypasses
the Linux-only syscall guard or authorizes a non-Linux filesystem move.

## Ownership requirements still not established

The runner flock excludes only cooperating processes using that lock inode.
It does not exclude Arr imports/upgrades/renames, manual shell moves, share
writers, other containers, or mount administration. A marker, configuration
boolean, inode match or operator-supplied root string does not prove exclusion.
A same-mount observation does not solve the source-entry substitution window.

Before gate 6 can close, the deployment must have a reviewed way to ensure
exclusive ownership of the relevant title entries during verification and
rename. Either all possible writers participate in enforceable coordination,
or the deployment provides an independently checked isolation/maintenance model.
The review must enumerate those writers and identify how failures are detected.
Do not implement an `exclusive_writers=true` flag that merely suppresses blockers.

## Crash and uncertain-commit policy

- Durable intent precedes any move. Failure to confirm it means no move.
- Loss of the in-process witness means no automatic move-completion claim.
- After restart, any unresolved intent stops the runner; never replay a move.
- A destination folder, matching inode/device, mount ID, or matching remote
  response alone cannot clear a crashed intent.
- Before a final commit, failures leave the original clocks and intent pending.
- An exception after commit requires reopening authoritative SQLite state. If the
  complete clock/Arr queue/intent transaction is present, do not repeat the move;
  if not, leave the move unresolved. Never restore stale JSON over newer state.
- The recovery path must preserve evidence and supply operator diagnostics. An
  operator-approved recovery operation still needs a distinct reviewed contract;
  no generic success flag can authorize clearance.

## Acceptance evidence still needed

1. Verify actual Unraid source/destination mounts and supported filesystem
   semantics without relying solely on share paths or device numbers.
2. Establish and test the complete external-writer ownership mechanism.
3. Run process-level crash/failure tests against that model, including unknown
   commit outcomes, mount/path substitution and source-entry replacement.
4. Review restart diagnostics and the explicit operator recovery procedure.
5. Then assess gate 7 using this accepted verifier before wiring gate 8.

The current mount increment advances item 1's executable checking, not all five
items. It does not complete a production gate, perform live service actions,
change the running container, authorize SQLite activation, or enable deletion.

## Deployment evidence collection after mount validation

The user reported **1,153 SQLite tests passed on Unraid**, with the same single
non-failing Requests warning, through `641144b`. This validates the new mount
binding and existing suite in disposable fixtures. Production writer ownership
is still not established.

The next review needs Docker mount and running-state metadata from the actual
server, not another synthetic ownership flag. Inventory all containers because
writers may include download/import tools as well as Radarr/Sonarr. Use a
formatted Docker inspect that exposes only names, running state and mount
source/destination/type/read-write flags. Do not dump full inspect JSON or
container environment variables: those may contain credentials.

This inventory is read-only and cannot prove exclusion. It establishes which
container mounts need closer review. Host processes, SMB/NFS clients, manual
shell access and privileged/mount-administration actors remain outside this
inventory. No pause/stop or mount-mode changes should occur during discovery.
Once paths are known, inspect their backing mounts and propose a concrete
writer-ownership model before production integration or approval.

## First deployment inventory findings

The supplied Unraid Docker inventory shows active writable media mounts in the
auditor, Radarr, Sonarr and Jellyfin. Jellyfin also has writable nested Movie/TV
bind mounts. Other stopped containers retain writable media mappings and could
become writers if started. Containers with Docker socket access also need to be
considered in the administrative trust model; a read-only socket bind is not an
API authorization policy. Host/share writers remain outside Docker inventory.

The host paths include both `/mnt/user/...` and `/mnt/media/...` forms. Their
backing relationship has not been established; matching relative names or device
numbers must not be used as proof. The raw complete user inventory is not copied
into the repository. No mount modes or running containers were changed.

`scripts/sqlite_deployment_path_probe.py` is a standard-library-only diagnostic
that can run through stdin in the existing auditor container. It imports no app
modules, starts no audit, reads no tracking database, lists no title contents and
calls no services. It selects only known path environment settings and the web
configuration's MEDIA_PATH field. It reports candidate stage paths and their
read-only directory metadata plus descriptor mount IDs when available. Missing
or aliased paths remain unavailable; unknown mount data is never reported as
same-mount evidence. It does not dump environment/config values or exceptions.

These are candidate defaults/overrides observed in a new diagnostic process,
not proof of the running audit subprocess's effective configuration (including
any dotenv or per-run changes). Config and writer exclusion remain explicitly
unverified. Remote Arr paths are declared strings, not verified mappings.

Run from the Unraid checkout after a clean fast-forward on feature/sqlite:

```sh
docker exec -i media_collection_auditor python -B - < scripts/sqlite_deployment_path_probe.py
```

The code is streamed into a separate diagnostic process, not installed into or
used to restart the running container. Local diagnostic tests: **16 passed,
1 Linux-only test skipped**, including secret-output exclusion, override
selection, unavailable/different mounts, path aliases and read-only inspection.
New deployment results are pending. Production gate 6 remains open.

## Auditor namespace stage-path result

The read-only deployment probe through `5b346cc` observed all eight candidate
movie/show stage directories. Within that auditor namespace they reported one
mount ID and device, and the declared Arr stage strings matched the default
`/media` layout. Web configuration was readable. Configuration authority and
writer exclusion correctly remained unverified; no production change followed.

The next environmental acceptance test uses the existing dedicated
`/mnt/user/sql_test` lab share. Earlier regression runs placed disposable
fixtures on container `/tmp`; they did not establish SQLite locking, directory
sync and no-replace behavior on this persistent Unraid lab storage.

Create a new unique rehearsal directory with mktemp, mount only it at `/lab`,
and direct pytest's basetemp to a previously nonexistent child. Keep virtualenv,
dependency downloads and temporary runtime files on tmpfs. Do not mount production
media or appdata. Preserve the rehearsal directory after both success and
failure; never point pytest's basetemp at an existing data directory, since pytest
owns/removes its fixture tree. This tests persistent lab storage, not production
mount equivalence or a full external-writer exclusion mechanism.

The user's SSH known_hosts replacement warning did not prevent the reported
fast-forward pull. No SSH configuration changes are part of SQLite development.
