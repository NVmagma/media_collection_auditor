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


## Portable copy intent durability

The user confirmed **11 copy tests passed on shfs and 11 on native Btrfs** through
`c771de8`. This resolves the observed empty-copy failure after independent cursor
isolation. It validates staging, not a completed move backend.

The next increment adds `stage_disposable_copy_with_intent` alongside the
primitive-only fixture helper. The durable wrapper requires a matching standard
tracking key and unique Waiting/source clock. Under the same lab lock it records
a distinct `copy_stage` intent before creating the private staging slot. Intent
contains source/staging bindings, source timestamp and content-manifest digest;
these are diagnostic bindings, not restart-clearance authority.

Successful copy verification checkpoints phase `applied_pending_reconciliation`
and detail `copy_phase: verified_source_retained`. Before completion it remains
`intent_recorded` with `copy_phase: prepared`. Every outcome keeps intent and
source. The wrapper reports intent persistence separately from lifecycle commit;
no clocks, Arr work, promotion or source removal are committed. Restart refuses
any new copy while any intent is pending. Partial slots are never overwritten.

Recovery status/inspection now recognizes the distinct copy kind and produces a
redacted manual-review report. It cannot be treated as a rename or remote Arr
success, does not call services, and does not authorize replay or clearance.
The existing HTTP recovery route does not accept copy-stage operations.

Tests cover intent-before-copy, crashes after intent/copy/verified checkpoint,
intent-checkpoint failure, partial copying, uncertain verified checkpoint both
before and after commit, restart refusal and safe read-only reporting. Related
local tests: **59 passed**. Fresh dual-filesystem validation is pending.

Durable phases do not yet implement resumable copying, completed publication,
metadata/permission preservation, guarded source cleanup or lifecycle/Arr commit.
Those remain the next portable protocol stages. Production and permanent
filesystem deletion remain disabled. API work stays on the product roadmap.

### Portable copy restart content inspection

`inspect_disposable_copy(root=...)` inspects only a marked disposable lab with
an existing durable copy intent. It validates the stored paths, tracking clock,
operation identifier and manifest digest before descriptor-relative content
reads. Parent symlinks are refused; two manifests and held-directory bindings
check for observable changes. Reports contain aggregate statuses, never title
names, paths or content digests. Inspection writes no SQLite state, copies no
files, clears no intent and authorizes no promotion, cleanup or recovery.
The existing cooperating-runner lock still applies; it does not exclude external
writers. Matching bytes are explicitly unverified historical identity and do not
establish fresh Jellyfin protections. Hashing complete retained copies is an
explicit diagnostic operation, unsuitable for ordinary dashboard/API polling.

Unraid confirmed the preceding durable-copy tests through `8c80c74`: 20 passed
on shfs and 20 on native Btrfs. Detailed restart inspection still requires its
own Unraid validation. Production remains JSON-authoritative and disabled for
SQLite activation; no completion gate advances from these results alone.

Unraid restart-inspection validation through `b3b329d`: 28 tests passed on shfs
and 28 on native Btrfs. Follow-up validation rejects inconsistent intent/copy
phase pairs and missing source clock bindings before reading content. Regression
coverage also replaces the source parent during hashing and changes the SQLite
revision during inspection: the former reports observed change, the latter
rejects the report as stale. These checks detect observable races; they do not
provide exclusion against arbitrary filesystem writers or an atomic snapshot
across independently scanned source and staging trees.

### Explicit operator inspection command

With the checkout on `PYTHONPATH`, run
`python -B scripts/sqlite_disposable_copy_inspect.py --root /absolute/disposable/lab`.
Use only an existing marked lab root containing state.db and a pending copy
intent. The command does not create a copy fixture or select a production path.
A valid JSON diagnostic exits 0 while its recovery status remains `blocked`;
inspection failures exit 2 with a fixed redacted reason, never exception text.
Read-only refers to media and SQLite state: the cooperating-runner lock requires
a writable lab mount. Full content hashing is explicit and potentially costly.
There are no resume, clear, promote, delete or activation switches.

Unraid confirmed the prior inspection hardening through `43c76e1`: 32 tests
passed on shfs and 32 on native Btrfs. These results do not advance production
activation, writer exclusion, or recovery authorization gates.

### Plan-bound portable staging

`stage_planned_disposable_copy` connects the existing advisory move planner to
source-retaining portable staging for Waiting-to-Holding/Keep candidates. It
copies the supplied bundle, validates one matching candidate and its time, checks
the SQLite revision under the lab lock, then recomputes the advisory plan after
source hashing and before recording intent. Missing fields, changed signals,
protected/noncandidate titles and stale revisions stop before staging writes.
Caller-provided signals remain untrusted for independent Jellyfin freshness.
This is a disposable parity integration, with no promotion, lifecycle checkpoint,
Arr request, source cleanup or production caller. Successful copies still leave
a pending intent for review; no recovery authority is introduced.

Unraid confirmed the operator inspection increment through `b51f2f2`: 39 tests
passed on both shfs and native Btrfs. Plan-bound staging requires its own Unraid
validation. Production activation and gates remain unchanged.

### Durable advisory transition binding

Plan-bound copies now persist a `plan_binding` containing the source revision,
source/destination stages and advisory observation time before copying. Source
observations must not predate the tracked source clock. Restart inspection
validates present bindings before content reads: revision must be an earlier
nonnegative integer, the source must be Waiting, destination Holding or Keep,
and the naive observation time must lie between the source clock and now.
Reports expose only whether a binding is available and the proposed destination
stage. Historical primitive-only copy intents remain inspectable with no plan
binding; absence never grants authority. This metadata is an advisory proposal,
not proof of historical protection freshness, a completed move, or permission
to promote/clear/clean up. No production execution changed.

Unraid confirmed plan-bound staging through `ca7b0e7`: 45 tests passed on each
of shfs and native Btrfs. Durable transition binding awaits its own server test.

### Source revalidation at the copy intent boundary

After advisory review and before the durable intent, copy staging repeats the
held-source manifest and metadata observation, checks the current source path
against the held directory, rejects aliases, and rechecks the SQLite snapshot.
Tests change file content, substitute a title directory, alias the source parent,
and advance SQLite during review; each stops before staging/intent creation.
This adds another complete source read in durable staging. It narrows an
observable review window but does not prevent changes after the last check or
exclude external writers. Existing post-copy verification and pending-intent
failure behavior remain required. No production move/cleanup is enabled.

Unraid confirmed durable transition binding through `56810b7`: 52 tests passed
on shfs and 52 on native Btrfs. Intent-boundary revalidation awaits server tests.

### Collected protections for portable staging

`run_collected_isolated_copy` shares the isolated move runner's collector/planner
logic under one lab lock. It enumerates complete title observations, binds the
candidate and revision, refreshes identity/signals before copy intent, and
requires unchanged observations. Missing/ambiguous data, changed protections,
transport failures and expired/reversed observation windows stop before intent.
After repeated source hashing it checks the observation window again, preventing
slow hashing from silently extending the budget. This means large titles may
require a different reviewed freshness design rather than a longer unsafe
window. No network-writing transport or production CLI is added; the fetch
callback remains trusted local input. Observations are experimentally bounded,
not independent production freshness or protection transactions.

The copy path accepts Waiting-to-Holding/Keep candidates only, rejects Arr
requests and retains source, tracking clocks and pending intent on success.
Pending operations precede network access and prevent automatic replay. The
rename path retains its existing behavior. External writer exclusion, promotion,
source cleanup and production integration remain unresolved.

Unraid confirmed source intent-boundary revalidation through `93ecbb0`: 56 tests
passed on each filesystem. Collected-copy tests use synthetic GET responses and
await Unraid validation; they do not assert a new live service test occurred.

### Whole-show portable staging coverage

Disposable collected-copy regressions now exercise a `TV/` tracking key with
specials, multiple populated seasons and an empty season directory. Successful
staging preserves the complete tree in both source and private staging while
retaining the original clock, leaving the copy intent pending and queuing no
Arr update. Refreshed keep-forever, keep-all-seasons, keep and favorite flags,
changed Series identity and ambiguous Series matches stop before staging.
These are whole-show synthetic collection tests, not season-pruning execution
or live Jellyfin validation. Existing show retention semantics are unchanged.

Unraid confirmed collected-copy integration through `e4e0942`: 65 tests passed
on shfs and 65 on native Btrfs. Whole-show regression coverage awaits server
validation. Production remains JSON-authoritative and SQLite-disabled.

### Descriptor-bound portable-copy parents

Portable staging now holds the lab root and source-stage parent as well as the
title directory through the full operation. Source and private staging opens
and staging-directory creation are relative to held descriptors. Root replacement
cannot redirect those creates into a replacement path. The source parent's
current root-relative entry and the title entry are rechecked before observation,
before intent, before copying, after copying/hashing and before the verified
checkpoint. Root fsync uses the held descriptor rather than reopening a path.

Adversarial tests replace the source parent with a symlink or another directory,
substitute a title symlink, and replace the root at staging creation. Each stops
before a verified checkpoint, preserves original tracking and any prepared
intent, and retains source/staging artifacts. Source-open failures close the
held descriptors. No restoration, cleanup or retry is attempted.

These are observed-boundary protections, not inode-conditional rename or atomic
filesystem/SQLite verification. Arbitrary external writers are still not
excluded, and no production move, portable promotion or source cleanup is
introduced. Gate 6 remains open.

Full Unraid baseline through `ac5d4a7`: 1,452 passed and 22 subtests passed on the
native disposable lab, with one non-failing Requests warning. The descriptor
increment requires its own targeted validation on both access paths; another
full run is not needed merely to repeat that unchanged baseline.

### Optional no-overwrite publication of retained lab copies

`publish_disposable_copy` accepts only an existing verified, plan-bound copy
intent in a marked lab. It rechecks the same SQLite revision, source/staging
content digest, held directory bindings and absent lifecycle destinations. A
publication marker is durably checkpointed before the kernel no-replace rename
of staging into the planned Holding/Keep directory. There is no ordinary rename
fallback. Unsupported capability or any uncertainty retains the source, copy
artifacts, original clocks and prepared publication marker; a second attempt is
blocked even after a known unsupported result.

After a successful rename, the live staging descriptor must match the published
entry. Source content/metadata and copy content are rechecked, parent directories
are fsynced and publication phase becomes `published_source_retained`. The source
is never retired, lifecycle tracking never advances, no Arr work is enqueued,
and the copy intent remains pending. This is an optional publication phase, not
a complete portable move backend. Other filesystems remain blocked at publication
until a separate safe strategy exists; no label whitelist is introduced.

Read-only copy inspection now validates publication metadata and reports the
published content status, including uncertain crashes after the rename but before
the phase checkpoint. Matching bytes do not clear the intent or authorize
recovery. Tests cover occupied destinations, prepared-intent crashes, unsupported
capability retention and actual Linux publication/uncertain checkpoints. The
capability test accepts only success or explicit kernel unsupported errors, never
an arbitrary failure as a pass. Actual publication crash cases require the
previously verified rename-capable native lab; the general retention/capability
checks run on both paths. No production caller or publication CLI is added.


### Application-owned writer coordination follow-up

The full native Unraid baseline now passes 1,583 tests and 22 subtests through
`fff83c0`. Inspection of the real JSON write paths found manual rescue did not
hold the shared audit/migration process lock. The next increment closes that
cooperating-application gap and rejects unsupported rescue backends. See the
[writer coordination contract](sqlite-writer-coordination.md). This does not
establish control over Arr, share clients or privileged administrators, nor does
the isolated SQLite root lock become a production coordination mechanism.
Gate 6 remains open and all implementation blockers remain authoritative.

### Nonblocking reads after file-entry substitution

A Gate 6 review outside the deferred NFS work found that the copy manifest and
copy loop checked a directory entry as regular, then opened it without
`O_NONBLOCK`. Replacement by a FIFO in that window could wait indefinitely for a
writer instead of returning an uncertain/pending failure. Both opens now use
`O_NOFOLLOW | O_NONBLOCK` and recheck the opened descriptor's regular-file type
and captured identity before reading or creating a destination payload.

Disposable child-process tests substitute a real FIFO, symlink or directory
between stat and open, at root and nested paths, during hashing, copying and
metadata verification. Each must reject without a FIFO writer and retain the
original fixture bytes. A separate durable-intent case verifies unchanged clocks,
no Arr work, no verified-copy claim and retained intent/artifacts after the race.
Children have a bounded parent-side timeout so a regression cannot hang pytest.

This narrows a concrete source-entry race failure mode. It does not prevent
arbitrary writer mutation, solve atomic source-entry fencing, bound all regular
file/storage I/O, authorize source cleanup or establish production ownership.
No NFS operation, production runner, deletion safeguard or backend selection is
changed. Local focused validation: 53 tests passed on macOS/Python 3.12; persistent
Unraid shfs/native acceptance remains pending.

The broader maintained local regression set also passes: 823 tests and 19
subtests on macOS/Python 3.12. This is not a claim of full native-Linux or Unraid
acceptance for the new race tests. No expensive CI/image build was triggered.

Tower subsequently accepted `108b8a3` on both persistent lab paths: 53 focused
checks passed on shfs and 53 on native Btrfs. The FIFO entry-substitution fix is
therefore accepted on those paths; production ownership remains unverified.

### Bounded startup marker validation

The follow-up Gate 6 read-boundary review found the isolated runner still read
its fixture marker by pathname before its already-safe descriptor check. The
maintenance journal also used an unbounded pathname byte read after lstat.
These could block on a substituted FIFO or consume an arbitrarily large marker.
The isolated runner now relies on its existing bounded, nonblocking held-marker
read, and its persistent lock open explicitly includes O_NONBLOCK. Maintenance
marker validation now uses a held root, no-follow/nonblocking marker descriptor,
a marker-length-plus-one read, before/after file identity checks and a root/entry
binding recheck. Descriptor cleanup happens on every exit.

Real child-process FIFO substitutions must stop before lock creation or operation
entry and preserve original marker/database bytes. Oversized-marker tests require
bounded descriptor reads and forbid pathname content reads. This is not an NFS
service test, production ownership fence, restart permit or all-I/O timeout.
Neither maintenance history nor production data is migrated or repaired. The
new startup cases and the previously accepted copy cases pass 87 focused tests
locally; Unraid acceptance for the marker increment remains pending.

Final maintained local validation passes 827 tests and 19 subtests. Root-alias
substitution retains the controlled RuntimeError contract and leaves the durable
request pending. The targeted startup acceptance command selects 48 marker,
maintenance-scope/controller/history and normal-lock reuse checks, avoiding a
repeat of the already-accepted 53 copy checks and native-only rename tests.
