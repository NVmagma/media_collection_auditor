# SQLite production move trust contract — blocked draft

**Current product requirement:** filesystem-independent media handling using
capability-based strategies. The earlier single-mount rename model is an optional
fast path, not the required deployment layout. The filesystem-name blacklist
described in the historical record below is superseded. See
[the product roadmap](product-roadmap.md) and the portability update at the end.

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


## Persistent lab result: required rename rejected

The fresh persistent Unraid lab run reported 1,125 passed and 34 failed. The
failure inventory consists of 21 direct unsupported-rename errors and 13 later-
phase assertions whose actual error is the same unsupported rename. The kernel
returned EINVAL for RENAME_NOREPLACE on both path-based and descriptor-relative
calls. The same application/syscall contract passed earlier tmpfs fixtures.

Linux requires underlying filesystem support for this flag and documents EINVAL
when a filesystem does not support a requested flag:
[rename(2)](https://www.man7.org/linux/man-pages/man2/renameat2.2.html).
The observed access path therefore fails the first execution model. Matching
mount/device observations cannot waive that failure.

Next collect read-only host findmnt metadata for the lab, media roots, and any
existing native lab share paths. A direct-filesystem candidate may permit a
separate disposable capability test, but that is not permission to change
production mounts or substitute /mnt/disk paths for /mnt/user paths. Do not mix
user-share and native paths within one move. A new candidate requires reviewed
mapping, same-mount checks, no-replace tests and the full relevant suite before
any release claim. Retain failed fixtures; do not reset pending operations just
to rerun the suite in the same directory. No unsafe fallback is introduced.

## Native Btrfs result and early shfs policy

The host findmnt evidence identifies `/mnt/user/sql_test` and the current user-
share media path as `fuse.shfs`, while `/mnt/media/sql_test` and its corresponding
native media path are Btrfs on the same observed pool. A fresh native Btrfs lab
run through `8cae0f5` reported **1,159 passed, one non-failing Requests warning**
in about four minutes. The earlier shfs lab run remains failed evidence, not a
result to discard. No production path was switched.

The next increment looks up filesystem type by the held descriptor mount ID in
`/proc/self/mountinfo`. Missing, malformed or ambiguous records fail closed.
`fuse.shfs` is explicitly blocked by the verified-deployment compatibility policy
before creating a move intent; there is no unsafe fallback or override boolean.
The filesystem type joins the in-process binding and is rechecked at operation
boundaries. This is a conservative compatibility policy for the observed system,
not a universal assertion about every future Unraid/kernel version.

Other filesystem labels are not a production approval. They still require the
no-replace syscall and every mount/path/witness/revision guard. A Btrfs lab pass
does not prove that native media paths cover all files in a user share, establish
exclusive writers, permit mixing native/user-share paths, or authorize changing
container mounts. Review all backing roots and per-title mapping before any
native-path production proposal.

Local focused checks: **69 passed, 12 Linux-only skipped**. Tests cover mount-ID
filesystem selection, missing/duplicate/malformed mount records, shfs rejection
and pre-intent/no-rename enforcement. Native Unraid focused validation for this
increment is pending. The regression command should keep using fresh uniquely
named native lab directories and preserve failed shfs artifacts.


## Portability requirement supersedes the filesystem-name policy

The user reported **81 focused tests passed** on native Btrfs through `1d52e27`
and clarified that the public application must not be governed by this deployment's
filesystem. The hardcoded fuse.shfs rejection has therefore been removed. This
change follows the product requirement, not an attempt to turn failed rename
tests green: the rename implementation still requires RENAME_NOREPLACE and
retains pending intent on unsupported/uncertain outcomes. It never falls back to
ordinary overwriting rename or source deletion. Filesystem type remains diagnostic.

The first portable component is `stage_disposable_verified_copy`. Under a marked
lab lock it rejects pending operations, inventories a source with held directory
handles, creates a private operation slot exclusively and copies files using
exclusive output creation. Symlinks and special files are rejected. It compares
recursive content digests and source identities before/after copying, checks
held path bindings, syncs the staged data/directories, and retains source and
tracking state. No renameat2 or filesystem-name check is used by this component.
Partial failures preserve staging; an occupied slot is never overwritten or
automatically resumed.

This is only copy staging. It deliberately does not promote a title, remove its
source, change lifecycle clocks, create an Arr notification or authorize recovery.
Permissions/extended metadata, durable copy-phase intents, restart reconciliation,
publication and guarded source cleanup still need a complete portable protocol.
External writer exclusion and service freshness remain open too. Do not present
successful staging as a completed move or universal filesystem certification.

Local checks: **57 passed, 9 Linux-only skipped**. New copy tests cover nested
content and empty directories, database/source preservation, occupied slots,
source mutation, symlinks, partial failure and pending-operation precedence.
Next validate this portable component on fresh dedicated lab directories through
both user-share and native paths. Production mounts remain unchanged.


## Portable staging validation: shfs passes, Btrfs mismatch under investigation

The dual-storage run through `ce1e30d` reported **7 passed on shfs**, then
**2 failed and 5 passed on native Btrfs**. Both Btrfs failures stop at the combined
final manifest/identity check, before promotion, source removal or tracking
commit. The occupied-slot test fails during its initial staging call, so it is
not evidence that overwrite protection failed. Neither result authorizes a
filesystem-specific exception or relaxation of content/identity verification.

The next diagnostic increment separates source-content equality, source-identity
metadata equality and destination-content equality, reporting only entry counts
and aggregate changed-field counts (device, inode, size, mtime, ctime). Directory
and file change counts are distinguished. No filenames, paths, content digests
or contents are included in the diagnostic summary. A mismatch still raises and
retains source/staging; there is no automatic retry or cleanup. Local tests:
**9 passed**, including diagnostic redaction and classification.

A fresh native-only targeted rerun is needed to identify which comparison fails;
filesystem behavior is not yet the established root cause. The shfs pass remains
valid evidence for the prior portable component; repeating the full unrelated
suite is not necessary for this diagnostic step. Preserve the existing artifacts.

## Cursor isolation correction for portable staging

The native diagnostic rerun through `cafd88a` reported 2 failed and 7 passed.
Both failures showed unchanged source content (four entries), unchanged source
metadata/identity and zero destination entries. This rules out metadata drift
as the reported failure and points to an empty copy traversal.

The next correction opens `.` relative to each held directory descriptor for
every enumeration and closes that independent scanning descriptor afterwards.
It does not enumerate the held source handle directly or use dup (which shares
an open-file description/cursor). This removes reliance on cursor effects from
prior manifest/enumeration passes. All original content and identity checks
remain mandatory; source retention, exclusive creation and tracking immutability
are unchanged. It is a traversal correction, not a filesystem-specific exception.

New regressions require enumeration to leave the held cursor untouched and
verify that repeated manifests do not prevent a later complete copy. Related
local checks: **61 passed, 9 Linux-only skipped**. Fresh shfs and Btrfs reruns are
needed to confirm the correction on the observed failing access path. A local
pass alone is not claimed as proof of the Btrfs root cause being resolved.
