# Initial production ownership model: operator-controlled maintenance window

The user confirmed that shares or host jobs can write to the media folders and
accepted a maintenance window as the initial design requirement. This is not
permission to stop services, disable exports/jobs, remount storage, update an
image, activate SQLite or delete media. Production remains JSON-authoritative.
Gate 6 is open; no ownership enforcer is implemented or approved yet.

## Selected first NFS adapter: full service pause

After the complete Unraid regression baseline, the operator confirmed that all
NFS shares may be temporarily unavailable during the initial window. This is
a design preference, not authorization to pause the service. The first adapter
will target a full NFS pause rather than independently rewriting export rules.
Other deployments can provide a different adapter with the same acceptance
contract; this is not an Unraid or filesystem restriction on storage logic.

The reviewed procedure must drain transfers before the boundary checkpoint,
persist intent in protected control storage, prevent automatic service restart,
request shutdown using the deployment's reviewed service mechanism, and verify
denial from a real client with both old handles and new connections. NFS pause
must cover state exports too. Docker/host writers still need separate controls;
Jellyfin's local read view and API must remain available. Do not enable a
maintenance permit from a process count or successful stop command alone.

Linux documents that NFSD shutdown discards server locks/state, and startup
enters grace periods. Restoration therefore must account for client state and
delayed requests; it is not an unconditional start in a cleanup handler. See
[kernel NFSD administration](https://docs.kernel.org/admin-guide/nfs/nfsd-admin-interfaces.html).
Reboot, service restart and controller/worker failure must not silently reopen
the protected scope. Host-specific persistent restart inhibition and recovery
remain unimplemented and must be reviewed before production use.

Before selecting executable service controls, gather the actual host version,
NFSD observations and candidate control-script identities with
`bash scripts/sqlite_nfs_pause_probe.sh`. It only reads fixed selected files and
hashes candidate scripts; it never sources or invokes them. Missing observations
remain explicitly unknown. A digest is discovery evidence, not reviewed code
or an executor allowlist. The next implementation must inspect/validate the
actual service mechanism, not guess it from historical script locations.

Real NFS shutdown/restart acceptance needs an isolated disposable Linux server
and client. A separate-kernel VM is one option, not a hard requirement: Linux
keys NFSD control filesystems to network namespaces. A reviewed namespace lab
may be possible, but an ordinary container alone does not prove correct control
mount or network isolation. Never reuse the host NFSD control mount, host
network or exported production paths for lab controls. Choose and verify the
test environment before executing service controls. No new image/build is
required for the host discovery probe.

### Reviewed host service script and namespace discovery

The user supplied Unraid `7.4.0-rc.1` observations: eight NFSD threads, NFSv3
and NFSv4.1/4.2 enabled, and both candidate service paths resolving to the same
script (SHA-256 `a2e6f7396e688a9dfbbe35e0f35c5839f1ee0a606b46ca1047bfa0b10e646fcf`).
The supplied script sources helper/default files and edits defaults before
dispatching its argument. Its `status` command is therefore unsuitable as a
read-only observation. Its stop function gates shutdown on mountd detection;
absent mountd can skip NFSD shutdown despite remaining threads. Stop completion
and the final script exit status are not independent pause verification. The
adapter must review sourced helpers/configuration and restart entry points too;
the main script digest alone does not bind their behavior.

The operator has no separate disposable Linux machine. Before attempting any
real service action, `scripts/sqlite_nfs_namespace_probe.sh` checks a possible
alternative: distinct ephemeral network and mount namespaces, private mount
propagation, and a new read-only NFSD control mount showing zero threads.
It never writes a control file, starts threads, invokes a service script,
changes exports or creates a network interface. Host thread counts are observed
before/after; a mismatch or unavailable capability blocks with no repair/retry.
It creates and removes only its own empty temporary directory and private mount.
This is a capability probe, not a real server/client or ownership test. Do not
add a fallback to host controls when namespace creation fails.

The kernel's [NFSD control filesystem implementation](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+/88afbb21d4b36fee6acaa167641f9f0fc122f01b/fs/nfsd/nfsctl.c)
keys the filesystem to the network namespace. Runtime observation is still
required for the actual host; this source does not establish that any arbitrary
container launch or namespace configuration is safe.

### Private NFSD thread-control lab

The user confirmed the namespace capability probe on Tower: distinct network
and mount namespaces, zero private threads, and eight host threads both before
and after. No server threads or service controls were written by that probe.

`scripts/sqlite_nfs_thread_lab.sh` is the next bounded acceptance step, not a
production pause adapter. It creates new private network/mount namespaces and
a new writable NFSD control mount. Before writing, it requires zero private
threads, a control identity different from the host's, the NFSD filesystem
magic and bound thread/version-file identities. Namespace and control bindings
are checked at action boundaries. No host service script is invoked.

The lab disables NFSv4 in its private instance to avoid exercising recovery
directory/upcall behavior in this step, then attempts two one-thread start/stop
cycles. It launches no mountd/rpcbind, adds no exports or network interfaces,
and mounts no clients or media. If the kernel requires additional userspace
support, startup can fail; there is deliberately no fallback to host RPC/NFSD
services. The bounded timeout and cleanup target only the private view. Lost
binding prevents further control writes; namespace teardown discards the lab.
Host thread observations must match before/after or the report stays blocked,
without any automatic host correction. Matching samples alone are not a proof
of external-writer exclusion.

Local inert-command tests cover both cycles, reused namespaces/control views,
nonzero initial threads, uncertain startup and lost control binding. They do
not start a kernel server. Actual thread-cycle evidence is pending on Unraid.
Real client denial, queued requests on restoration, NFSv4 behavior, restart
inhibition and container fencing remain unverified and required for gate 6.

### Real NFSv3 RPC client acceptance lab

The user confirmed `45be857` on Tower: two private thread cycles reached one
running thread and zero stopped threads, while host threads remained eight.
This verifies private thread control, not client denial or a production fence.

`scripts/sqlite_nfs_client_lab.sh EXISTING_ABSOLUTE_LAB_PARENT` is the next
bounded acceptance step. It creates a new retained fixture directory and a
read-only, capability-dropped Python container using the already-reviewed
cached image (`--pull=never`). The container has no network interfaces except
its private loopback and sees only the checkout read-only and fixture control
directory; the server's data directory is not mounted into the client.

The server joins that private network, then creates distinct PID and mount
namespaces with private propagation. Before RPC helpers or exports run, it
hides host `/etc`, `/var/lib`, `/run` and (when separate) `/var/run` behind
private configuration/state views. It clears socket-activation variables,
mounts a new NFSD control view, binds its identity and requires zero threads.
Private export configuration grants only loopback access to the new fixture
data directory. Private rpcbind/mountd run under the disposable PID namespace;
kernel service controls and cache updates are confined to the private network.
No host service script, Docker socket in the client, package install, image
build or production export is used. PID namespace teardown ends lab helpers.

The raw Python client implements bounded TCP RPC framing and only MOUNT,
LOOKUP and eight-byte FILE_SYNC WRITE requests. It keeps an old RPC connection
and file handle for the pause test and also tries a distinct new-connection
probe. It bypasses the kernel NFS client, so LOCALIO cannot bypass NFSD in this
test. The server independently hashes fixture bytes before/while paused and
after an explicit fresh write following lab restoration. An uncertain paused
transport outcome is not permanent denial and is never blindly retried. A
malformed reply cannot be counted as successful denial.

References: [NFSv3 protocol](https://www.rfc-editor.org/info/rfc1813/),
[RPC framing](https://www.rfc-editor.org/info/rfc5531/), and
[LOCALIO behavior](https://docs.kernel.org/filesystems/nfs/localio.html).
The fixed payloads, loopback-only destination, bounded reply lengths/deadlines
and namespace guard are lab constraints, not a public NFS client feature.

On failure, logs/control/data are retained and no host service correction or
write retry is attempted. Host NFSD thread count and export/etab hashes must
match before/after. These observations supplement the namespace boundary; they
are not standalone ownership evidence. Actual client-lab execution on Unraid
is pending. Even a passing result will not cover NFSv4, Mac/kernel client
writeback, all delayed requests, persistent restart inhibition or other writers.
Those remain requirements before production ownership can be granted.

## Implemented disposable journal foundation

`app/sqlite_disposable_maintenance_journal.py` creates only new fixture roots.
It records an ordered SQLite history: prepared, fence requested, fixture fenced,
work pending, outcomes verified, release requested, released. Every advance
requires the current integer revision and a nonblocking controller process lock.
Skipped/replayed transitions and invalid histories fail closed. Durable commits
use SQLite FULL synchronization; creation synchronizes the fixture directory
and its parent. Unsupported synchronization fails rather than being ignored.

Inspection opens an existing marked fixture read-only, never creates a missing
database and never resumes/replays/releases anything. Forced process-exit tests
retain each committed pending phase, and interrupted uncommitted changes leave
the previous phase available for review. Records always report production
authorization and external writer verification as false, even at completion.

This is the journal foundation, not a working NFS/container controller: fixture
phases are explicitly chosen rehearsal records and do not execute or verify
their corresponding external action. The fixture directory must be trusted
against unrelated writers during these tests; its marker and advisory lock are
not a security boundary against an external process replacing files. Real
scope binding, enforcement, administrative isolation and independently verified
outcomes remain necessary before production integration.

### Synthetic controller action ordering

`app/sqlite_disposable_maintenance_controller.py` now holds one controller lock
across a committed request, an exclusive durable fixture receipt, and its
completion checkpoint. Fence and release are explicit separate operations;
release requires the journal's verified-outcome phase. Lock identity is checked
before and after the synthetic action. The module accepts no external command
or arbitrary adapter callback and changes no export, service or media path.

If the action fails, process exits after its receipt, or lock identity changes,
the committed request remains pending. The controller refuses to replay a
pending request even when the receipt exists. Receipts are never overwritten or
deleted; inspection does not infer recovery authority from them. A receipt is
only a test artifact and does not deny writes. This tests action ordering, not
external ownership or a working enforcement backend.

### Fixture scope and receipt binding

New journals persist the canonical fixture path and the directory/database
device/inode identities. Inspection and controller boundaries reject missing
bindings or copied/replaced scopes. The controller rechecks the binding and
fixture marker before its synthetic action and before committing an outcome.
It also independently verifies the exclusive receipt's identity, exact bytes
and metadata; symlinks, hard links, replacement and missing receipts fail.
An action followed by verification failure retains its durable pending request.

These identities bind a disposable rehearsal to its observed scope, not to a
filesystem brand. A filesystem that cannot preserve the required observations
fails closed; there is no filesystem-name allowlist or identity bypass. This
is not a proof against malicious concurrent file replacement, nor an external
write fence. The trusted fixture-directory requirement still applies.
Previous disposable journals without bindings are intentionally not upgraded
or assigned a new scope automatically. Copies, relocations and changed identity
after restart require review, not automatic reattachment or replay.

### Cooperative writer acceptance harness

`app/sqlite_disposable_maintenance_writer.py` opens only the fixed
`writer.fixture` file in a marked, bound lab. Each bounded write takes the same
controller lock and checks the durable journal before writing, including when
its descriptor was opened before maintenance. Prepared and explicitly released
fixtures permit writes; every pending phase denies them. File identity is
rechecked so an old descriptor cannot silently write a replaced fixture file.

Subprocess tests cover a live writer holding an old descriptor and a controller
that exits after its synthetic action but before outcome commit. Pending
history continues denying cooperative writes after process locks disappear.
This is a cooperative fixture protocol only: ordinary file writes, NFS clients
and containers do not honor it and remain unconstrained. It cannot supply the
external ownership evidence required by gate 6. No public maintenance API or
production writer is wired to it.

The consolidated runner's `--maintenance-only` mode runs the focused journal,
controller, scope, cooperative writer, process-lock and production-guard tests
without publication capability flags. Use a new disposable basetemp each time.

## Scope and required enforcement

A maintenance window must cover the selected source and destination parents,
private staging/retention paths, tracking state and every route that can write
those objects. Different path spellings, bind mounts and union/native paths
must be accounted for; pathname similarity is not an alias proof. If mappings
are uncertain, treat potentially overlapping access as in scope or block.

The accepted deployment must identify its trusted administrators and who can
change mounts, shares, schedules or containers. Ordinary automation must not
be able to restore write access while a maintenance operation owns the scope.
A reviewed administrative trust boundary is required; a claim that no job is
currently running is not an enforcement mechanism.

| Participant | Required maintenance property | Evidence still needed |
| --- | --- | --- |
| Auditor workers and manual rescue | One agreed process lock and backend/configuration binding; competing runs cannot enter | Shared physical lock mapping across instances; new rescue checks already passed on both lab paths |
| Radarr/Sonarr and import/download automation | No uncontrolled write route into the scoped media; automatic restart/import cannot reopen one | Actual mounts, restart policies, relevant schedulers and a chosen fence |
| Jellyfin and other metadata/media tools | No writable scoped media route; fresh protection reads remain available | Read-only media view or an accepted equivalent that covers nested mounts and existing handles |
| SMB/NFS clients | Write access is denied for the scope, including existing clients/handles and reconnects | Protocol/export mapping and a verified denial mechanism |
| Host jobs/manual transfers | Relevant jobs are drained and cannot restart or bypass the boundary through another path/account | Job names/schedulers, access identities and enforcement mechanism |
| Administrative/container-management access | Cannot silently invalidate the reviewed boundary under normal automation | Privileged containers, Docker API access and permitted maintenance administrators |

Stopping every container is not a complete plan: fresh Jellyfin protection
collection still needs a live service, and host/share writers exist outside
Docker. A read-only bind of the Docker socket does not make its API read-only.
Restart-policy snapshots, quiet queues, `lsof` output, process counts, permissions
samples or a signed operator checklist cannot independently authorize moves.
Already-open writers matter; changing a configuration value or a pathname's
permissions alone is not proof that their writes have been denied.

## Required operation ordering

1. Prepare an explicit scope and writer inventory with no media/service changes.
   Reject unknown routes or privileged bypasses that have not been addressed.
2. Review concrete enforcement and restoration steps for that scope. Obtain
   explicit approval before applying them. The application must not acquire
   unrestricted Docker/host control merely to run an audit.
3. Apply and independently verify the boundary, including restart prevention
   and existing-handle behavior. Prove it first against disposable media with
   actual writer processes. Boolean acknowledgements are not a verifier.
4. Bind the live operation to that verified scope and current roots/configuration,
   then obtain fresh protections and a current SQLite plan. Durable intent must
   precede each filesystem action. Loss of ownership prevents further actions;
   after intent it also leaves the operation pending.
5. Keep the boundary valid through final verification and the atomic tracking/
   queue/retained-original/intent checkpoint. The existing hash, path, revision,
   source-entry and no-overwrite checks remain required, even during maintenance.
6. Inspect outcomes before restoration. A process crash or unknown commit must
   not automatically reopen writers, replay moves or clear intents. Restore
   access only through the reviewed operator recovery procedure. Original bytes
   remain retained; permanent deletion remains separately disabled.

The maintenance mechanism must fail closed if its controller dies or its scope
cannot be verified. A sampled "all stopped" response followed by unrestricted
restart authority is insufficient. The controller contract, enforcement backend,
failure behavior and recovery implementation are the next development work;
this document is not an executable permit or a new activation flag.

## Portability and remaining gates

This is a deployment ownership requirement, not an Unraid/Btrfs requirement.
Enforcement can vary by deployment, but its observable safety contract must be
the same. Unraid discovery below is only a deployment-specific diagnostic.
Filesystem capabilities still govern which move strategy is available: accepting
maintenance does not waive no-replace requirements or enable an ordinary rename
fallback on shfs. A safe alternative strategy for unsupported capabilities,
production orchestration, protection/Arr verification, restart clearance and
release-image validation remain unfinished. No gate closes from the window
preference or from an inventory alone.

## Next read-only deployment input

The earlier Docker inventory showed writable media routes in the auditor, Arr
and Jellyfin, additional/stopped media mappings, and Docker-socket consumers.
It is historical evidence, not proof of current ownership. Refresh only selected
metadata with:

```bash
bash scripts/sqlite_writer_inventory.sh media_storage
```

The script lists all containers' mounts, running/paused state, restart policy,
privileged/PID/capability settings, and four share export/security fields. It
does not read environment variables, service keys, raw cron commands or media
contents, and it makes no configuration changes. It always reports writer
exclusion as unverified. Missing access stays explicitly incomplete.

The operator must additionally identify the SMB/NFS protocols in use and the
names/schedulers of relevant host jobs or manual transfers. Names and their
write destinations are sufficient for review; do not paste secrets or complete
job command lines. These inputs let us propose specific changes and a restore
procedure for approval before touching the running deployment.

## Review of the supplied current deployment inventory

The refreshed selected-field inventory is sufficient to classify container
control requirements, but not to grant ownership. The raw container inventory,
private paths and unrelated application configuration are not copied here.

| Observed role | Proposed maintenance control to review | Required verification before moves |
| --- | --- | --- |
| Active auditor with writable media and tracking mounts | Fence the existing writer during cutover; allow only the approved worker to own the move scope | Deployed revision/configuration and shared lock identity; lab checkout tests do not identify the running image |
| Active Radarr/Sonarr with broad writable media views and automatic restart policies | Deny scoped media writes and prevent uncontrolled restoration/restart | Every overlapping mount/alias and existing writer handle is covered; API path reconciliation can still be completed safely |
| Active Jellyfin with broad and nested writable media views | Provide a reviewed read-only media profile while keeping protection API/config/cache available | Both parent and nested media views deny writes; fresh protection collection still succeeds |
| Stopped ripper with broad media access, privileged mode and an automatic restart policy | Include it in restart/admin control; stopped state alone does not remove it from scope | It cannot start and regain scoped write or administrative access during the window |
| Stopped music manager with a broad media view | Keep the potential write route fenced until normal restoration | Its broad view is accounted for even though its intended content differs |
| Download/audio tools with writable media subdirectories | Classify actual overlap and indirect import routes before deciding which require fencing | No inference that a similarly named subtree is isolated; unrelated verified scopes need not be stopped |
| Dashboard/container-management clients with Docker socket mounts | Review their administrative authority and prevent automation from reopening fenced writers | A read-only socket bind is not proof of a read-only Docker API |
| Network shares | Establish effective protocol/export/access rules and deny scoped writes through the window | Existing clients/handles and reconnects cannot write; selected share settings alone do not prove this |
| Host jobs/manual transfers | Operator identifies Arr and occasional Mac copies over NFS; no scheduled host job identified | Known routes must be fenced; this statement does not establish exhaustive absence of other writers |

No listed container is automatically authorized for stopping, recreation or
mount changes. An absent added-capability list or non-privileged setting does
not establish complete containment. Likewise `restart=no` does not exclude
host schedules, management tools or manual starts. Container snapshots remain
observations, not a continuously enforced boundary.

### Service availability and restoration ordering

Prefer an independently verified denial of scoped media writes while required
read APIs remain available. Jellyfin cannot simply be stopped and replaced with
cached protection data. For Arr, any maintenance profile must also support safe
path/monitoring reconciliation after the filesystem checkpoint. The existing
client requests `moveFiles=false`, but that request field is not proof of service
behavior or an independently verified Arr outcome.

Do not restore Arr filesystem write access while its path outcome is unresolved:
a restart into stale paths can reintroduce the competing writer before handoff
is complete. Pending queue/outcome verification, fresh protection collection,
worker ownership and restoration must be designed together. Those production
integrations and their failure ordering are still unimplemented/unapproved.

### Next implementation acceptance work

1. Finish the host/share writer map and identify the exact enforcement backend
   and administrative boundary. Do not substitute a checklist acknowledgement
   or a period of quiet activity for write denial.
2. Build its controller and persistent maintenance journal against disposable
   services/storage first. It must own scope identity and restart prevention;
   observer metadata is not an executor permit.
3. Exercise old and new writer handles, alternate paths, queued imports, client
   reconnects, controller/worker crashes and unknown SQLite/Arr outcomes. Loss
   of control must preserve the fence and pending evidence, not restore access
   automatically.
4. Only after that review, propose the concrete production entry/exit procedure
   and request approval to apply it. Existing move capability checks, blocked
   production backend and separately disabled deletion remain authoritative.

### NFS route identified by the operator

The operator identifies the normal writers as the Arr stack and occasional
manual copies from a Mac laptop or Mac mini, using NFS. No scheduled host job
has been identified; this is not evidence that every possible writer is absent.
Write frequency does not change the ownership requirement. NFS is a deployment
adapter requirement, not an application filesystem requirement.

Before choosing that adapter, inspect the server's current export list with
`exportfs -v` (no other flags or path arguments). This displays export options;
it does not reload or change exports. Review parent, nested and alternate-path
exports as well as the apparent media export. Client selectors and options must
remain distinguishable if private hostnames/addresses are redacted. See the
[exportfs manual](https://www.man7.org/linux/man-pages/man8/exportfs.8.html)
and [exports manual](https://www.man7.org/linux/man-pages/man5/exports.5.html).

That listing is discovery evidence, not proof of a write fence. A future entry
procedure must drain ongoing manual transfers before establishing the protected
checkpoint, and enforce scoped write denial through verification and handoff.
Disposable acceptance must cover pre-existing client handles, delayed writes
and reconnects, alongside alternate exports and local container routes. Neither
a client promise to stop copying nor an export configuration snapshot grants
execution authority. Export changes, client unmounts and service restarts still
require a concrete reviewed procedure and approval; none are performed here.

### Review of supplied NFS export evidence

The supplied current export listing includes writable, world-selector exports
for both the media share and the appdata share. Its `sec=sys`, `all_squash`,
`anonuid=99` and `anongid=100` options map client identities; squashing is not
write denial. Do not infer Internet reachability or successful file access from
the selector: network reachability and server filesystem permissions remain
separate. Unrelated share names and their raw inventory are omitted here.

The appdata route expands the required boundary beyond media bytes: state,
locks, intents and maintenance evidence must not be writable through a share
alias by an excluded participant. A local advisory lock does not independently
exclude a client that writes without taking it. The supplied listing shows no
separate nested media export, but it does not prove physical alias isolation or
exclude another protocol or subsequent configuration change.

The initial adapter proposal is server-side denial of NFS writes to every
export that overlaps the chosen media **or state/control** scope, combined with
the container controls above. Do not implement this as a per-Mac identity
exception: the current client selector is broad, and the configured identity
mapping is shared. This remains a proposal, not a verified enforcement backend.
Prefer a private, unexported control directory with restricted administrative
write access for the maintenance journal; moving production state there is a
separate migration requiring review, not an incidental diagnostic action.

Before any production procedure, implement and test this adapter against a
disposable NFS server/client and disposable container mounts. The acceptance
matrix must include:

| Case | Required result |
| --- | --- |
| Client has a file open before entry, or has a transfer in progress | Drain is explicit; after the boundary checkpoint, further scoped writes are denied |
| Existing client reconnects, or a different permitted client connects | Scoped writes remain denied; fresh read APIs remain available |
| Client writes state, lock or journal through an exported parent/alias | Denied independently of cooperative application locking |
| Container uses broad, nested or native-path media access | Every overlapping route is fenced; an NFS-only change is insufficient |
| Export/container configuration changes during ownership | Ownership becomes invalid and the worker stops before its next action; pending evidence is preserved |
| Controller or worker exits, or commit/Arr outcome is unknown | No automatic write restoration, move replay or intent clearing |
| Operator restores after verified outcomes | Reviewed original configuration is restored without overwriting intervening administrative changes |

No additional production discovery command is needed from this listing alone.
The next development step is the isolated controller/journal and adapter
acceptance harness. Export mutation commands are intentionally not supplied as
an operator action before that implementation and review.
