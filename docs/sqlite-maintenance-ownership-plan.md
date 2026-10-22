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

### Controller-death scenario with retained SQLite intent

The user confirmed the ordinary NFSv3 client lab through `2f2e039`: fixture bytes
stay unchanged while paused, a fresh explicit write succeeds after restoration,
host threads remain eight, and production export/etab hashes match. The client
reports uncertain paused transport outcomes and zero automatic retries. This
establishes only that isolated NFSv3 roundtrip, not production ownership.

The optional `--controller-crash` scenario creates a new disposable SQLite
journal under the client control directory and commits `fence_requested`
before its readiness signal allows a separate pause worker to act. The lab
supervisor must be PID 1 of its new PID namespace. Once paused transport probes
finish, the supervisor kills only its own pause-worker child and verifies the
expected signal exit. RPC helpers and the namespace supervisor remain alive.

After that death, an independent new RPC connection must still fail to complete
a distinct fixture write, the private NFSD count must remain zero and the
fixture hash must remain unchanged. The client inspects the SQLite journal and
requires revision 1/`fence_requested`; it never advances or clears the request
from observed bytes or pause. No restoration is attempted in this scenario.
Artifacts remain for review after temporary lab/container teardown. The
journal's stored path refers to its client-side `/control` fixture view; it
must not be automatically rebound or promoted into a production recovery permit.

Local tests cover actual durable journal ordering, unexpected successful RPC
writes after death, changed/preexisting journals, and the real shell worker's
SIGKILL behavior using regular files. The actual NFSD controller-death run is
pending on Unraid. This is a failure-ordering rehearsal; it does not bind a
trusted production enforcer to journal authority or prevent another trusted
administrator/service from restarting NFSD. Persistent restart inhibition,
NFSv4/kernel-client writeback and other writer fences remain unimplemented.

### Restart entry-point review after successful controller death

The user confirmed the `6fab460` death scenario: private threads remain zero,
fixture hashes stay unchanged, intent remains pending and no restoration occurs;
host threads/export hashes remain unchanged. The next gap is preventing other
ordinary service controllers from reopening NFS while maintenance owns scope.

Official source revision `26eb1b5c1d547ddbf44a38e63956ba24f659098b` has an
`rc.nfsd` SHA-256 exactly matching the script supplied from Tower. This anchors
the main-script review; it does not establish that every installed helper or
custom startup path matches that revision. Reviewed related sources show:

* [NFS settings apply](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/emhttp/plugins/dynamix/scripts/nfsSettings)
  writes the persistent defaults and can call `rc.nfsd restart` based on its
  status response. A thread-only pause with mountd alive can leave this route
  able to restart the server.
* [Network-service reload](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/emhttp/plugins/dynamix/scripts/reload_services)
  can dispatch `rc.nfsd update`; the main script can then restart for changed
  interface binding. A cooperative auditor lock does not cover this route.
* The [NFS settings page](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/emhttp/plugins/dynamix/NFS.page)
  exposes the `shareNFSEnabled` preference. That preference is not checked by
  the reviewed `rc.nfsd start` itself. A preference snapshot or writing `no`
  alone is therefore not independent proof that all restart routes are denied.

Before choosing a production mechanism, collect only that selected preference
from persistent/runtime settings and installed hashes for the six reviewed
service/UI files with `bash scripts/sqlite_nfs_restart_probe.sh`. The probe
never sources helpers/configuration, invokes service subcommands, dumps other
settings, changes configuration or treats matching hashes as a restart permit.
Missing/duplicate/unrecognized preference values remain unverified.

The remaining design must cover settings apply, network update, boot/array
startup, script replacement/upgrade and permitted administrative access, while
preserving a protected pending journal and avoiding unconditional restoration.
Unreviewed startup/custom-script routes remain unknown. No host wrapper,
configuration edit, plugin or boot hook is installed by this discovery step.

### Installed-source confirmation and private entry-point guard

The user confirmed persistent and runtime `shareNFSEnabled=yes` and matching
hashes for all six reviewed source files through `41bd286`. That confirms
reviewed bytes, not a continuous restart fence or complete startup inventory.

`--restart-guard` extends the private client lab after controller death. Its
deny-only guard returns 75 for every dispatch, including stop/status and unknown
arguments, before any original helper/default sourcing. Bash privileged mode
ignores environment startup hooks and imported functions. There is no delegation
path, timer expiry, journal-derived allow flag or automatic restoration. Only
the lab installs it, as read-only private bind mounts at both known rc.nfsd
paths. The source file remains outside the client's control/data mounts.

The lab independently verifies zero NFSD threads after 12 denied dispatches,
then exercises exact-hash copies of the installed settings and network-update
scripts. Settings writes hit private `/boot`; queue commands use a fixture
queue and private spool; unrelated service dispatches and logger are inert
private fixtures. The host's configuration, queue and original service file
are not modified. The outer harness also compares host service/share-config
hashes in addition to thread/export observations. Unknown reviewed-source hashes
fail before any copied service code runs.

After those attempts, a new independent RPC write must still be unavailable,
fixture hashes must remain unchanged and the SQLite request must remain pending.
Local maintained checks pass 528 tests/19 subtests, including guard environment
and dispatch cases. The user confirmed private entry-point acceptance on Unraid: 12 dispatches
were denied, both reviewed update paths left threads zero, the journal remained
pending and host threads stayed eight.

This is not a host guard installer and does not establish persistent restart
inhibition. Private mounts disappear with the lab; production boot ordering,
upgrade/replacement, direct privileged daemon/control access and other writer
routes remain unresolved. Production reports must keep restart inhibition and
writer exclusion false. The guard deliberately blocks stop/status as well;
a production enforcer would require separate reviewed pause/observation paths
and explicit installation/restoration approval.

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

### Cold-start source review and remaining deployment requirement

At the same pinned upstream revision, `rc.M` invokes `rc.inet2` before
`rc.local`. The NFS server startup stanza in `rc.inet2` is commented out with
an explicit note that emhttpd brings up enabled NFS. This describes these
reviewed shell bytes, not a verified inventory of every startup actor.
`rc.local` installs plugins before invoking `go` (or `go.safemode`) or its
fallback emhttp launch, but Safe Mode skips package/plugin installation.
A plugin-only guard therefore cannot establish coverage across boot modes.
Neither a successful normal boot rehearsal nor a retained journal can repair
that omission. The manager's internal startup and third-party startup actors
remain outside this source review.

The read-only restart probe now hashes `rc.S`, `rc.M`, `rc.inet2` and `rc.local`
as well. It never sources those files, reads custom go contents, invokes the
manager or changes startup preferences. The user confirmed all ten installed source hashes match, including the four
boot scripts; both selected NFS preferences remain enabled. Hash agreement does not prove an early,
persistent fence. The deployment design must deny automatic service startup
before any writer can resume, including Safe Mode, missing/corrupt durable
intent, upgrade/replacement and failed guard installation. Unknown boot state
must retain pending work and require explicit recovery; it cannot automatically
release the fence. No host installer or reboot test is supplied at this stage.

Reviewed sources:
[rc.M](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/etc/rc.d/rc.M),
[rc.inet2](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/etc/rc.d/rc.inet2),
[rc.local](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/etc/rc.d/rc.local).

### Linux boot binding for retained NFS fixture intent

New NFS crash/guard fixtures require `bind_linux_boot=True` when creating their
journal. The kernel boot UUID is captured before creating the fixture and
stored with its existing path/device/inode binding. Each controller boundary
and inspection rechecks that UUID. Missing, malformed or changed kernel identity
blocks further transitions, synthetic actions and release; committed intent is
retained. Reading is bounded and accepts only a nonzero canonical UUID from
Linux's fixed `/proc/sys/kernel/random/boot_id` interface. There is no fallback
to timestamps, hostnames or caller-supplied identifiers.

The NFS client also requires a boot-bound journal when inspecting pending
intent: a portable path-only synthetic fixture cannot satisfy acceptance.
Its successful report identifies `journal_scope=current_linux_boot`, never a
production permit. Portable synthetic journal tests still support path-only
bindings. Old fixture databases without the boot-binding column are rejected
without automatic schema migration, rebinding or replay; their files remain
available for offline review. Always create a new lab through the harness.

Regression tests simulate boot drift at every checkpoint and after a synthetic
action, verify no completion/release or receipt is inferred, and check database
bytes remain unchanged on rejected inspection/recovery. Simulated identities
test the decision logic. The user confirmed the live Linux boot-bound guard
fixture through `32f2490`: pending intent retained, all 12 dispatches denied,
no restoration and host threads unchanged at eight. These checks do not reboot Tower, persist a guard, stop
startup services, prove NFSv4/kernel-client exclusion, or close Gate 6. Host
boot fencing and any eventual production restart-clearance implementation
remain separate requirements.

### Network namespace binding and independent read-only rejection

Linux NFSD state is scoped to its network namespace. New Linux-bound fixtures
therefore store the observed network namespace identity alongside the boot
UUID and path/device/inode binding. Every controller boundary and inspection
requires both identities to match. Missing/invalid identity is not replaced
with a host name, PID or supplied flag. A changed namespace raises a distinct
scope error before further transitions or synthetic receipts; intent remains
pending. Older fixture formats are retained without migration or rebinding.
Portable path-only synthetic fixtures continue to grant no external authority.

`scripts/sqlite_maintenance_scope_lab.sh` checks the actual Linux interfaces
using two new cached-image containers with separate `--network none` networks,
read-only root filesystems and all capabilities dropped. The first creates a
new pending boot/network-bound fixture and stays alive for a bounded interval.
The second receives only read-only source/control mounts and must reject that
same physical database with the specific network-scope error. Other failures
(including boot mismatch or an unavailable database) fail the check rather than
being reported as successful rejection. The harness verifies unchanged database
bytes and that the first container remained alive; cleanup removes only its
two newly created containers and retains the pending fixture.

Keeping the original namespace alive prevents namespace identifier recycling
during this check. A stored namespace identifier alone is not a durable kernel
reference: it can be recycled after the original namespace disappears. This
binding is an additional rejection check, never proof of continuous ownership
or a production permit. Production still needs independently held enforcement
and scope references, restart inhibition and explicit recovery. This harness
never starts/stops NFS, mounts a kernel client, changes exports or configuration,
reboots Tower, grants restart clearance or closes Gate 6.

### Accepted namespace rejection and retained-journal review

The user confirmed the two-container scope lab through `c73297a`: the new
namespace was rejected, the physical journal bytes were unchanged and no NFS
control/configuration was touched. This accepts the bounded scope-rejection
scenario; it does not establish continuous namespace ownership or fencing.

`app/sqlite_maintenance_review.py` and its read-only CLI support reviewing a
retained marked fixture after its original container/namespace disappears or
its mount path changes. This API is separate from strict operational inspection:
operational transitions still reject binding drift. The review reports validated
phase/revision and categorical path/boot/network observations, never raw stored
paths, boot UUIDs or namespace identifiers. It always denies resume, clearance,
production authorization, restart inhibition and writer exclusion, including
when every observed binding matches or a synthetic history reached released.
An exit code of zero means only that fixture history could be read.

The source is opened read-only without following a database symlink, checked
for a single regular-file link and stable path/file metadata, and read into a
bounded one-MiB image. SQLite queries only that detached image in memory with
query-only mode and memory temporary storage; it never opens the source database
or creates a controller lock or SQLite sidecars beside it. Existing rollback,
WAL or shared-memory sidecars block review without deletion, recovery or
checkpointing. Unsupported detached-deserialization capability fails closed.
Missing/unmarked/aliased roots, oversized data, source replacement and invalid
history cannot become clearance. Old schemas can be described as unavailable
without migration or rebinding. The original evidence is retained.

On Unraid, mount only the selected retained fixture at `/review:ro` and the
checkout at `/src:ro` in the cached Python lab image, with network disabled,
a read-only container root, all capabilities dropped and no-new-privileges.
Run `python -B /src/scripts/sqlite_maintenance_review.py --root /review` with
`PYTHONPATH=/src`. A relocated path or different network is expected evidence
for this report, not permission to resume. Gate 6 remains open.

### Read-only review accepted; process-session continuity required for transitions

The user confirmed retained-journal review through `f2c9238`: valid history at
revision one / fence requested, path mismatch, and no resume or clearance.
Boot and network identifiers matched in the later reviewing container. Such
matching observations cannot establish that the original namespace or controller
remained alive; identifiers may be reused. The review now explicitly reports
`scope_comparison=identifiers_only` and `controller_session_verified=false`.

New Linux-bound fixtures additionally store their creating process PID and a
fresh in-memory identifier generated when the journal module starts. Transition
boundaries compare both with the current process. A new interpreter cannot load
its session identifier from the journal, and a fork cannot inherit authority
through copied module memory because its PID differs. PID reuse alone also
cannot transfer a session. Missing or invalid session metadata blocks operations
without automatic migration or rebinding. Session drift after a synthetic action
retains the committed request without recording completion. Portable path-only
synthetic fixtures remain non-authorizing ordering rehearsals.

Strict boot/network inspection and detached review remain available for reading;
neither grants transition authority. The stored identifier is not a credential
or a defense against a privileged/hostile process modifying Python or SQLite.
This is an additional guard against accidental process/restart inheritance,
not independent writer exclusion, persistent kernel ownership or permission
for production operations. There is no automatic takeover/release API.

The scope harness now also runs a second Python interpreter inside the original
container, so boot, namespace and path identities deliberately match. Its attempt
to advance the new disposable pending fixture must fail with the specific
controller-session error, leaving database bytes unchanged. Only then does the
existing separate-network read-only check run. Both original containers are
removed by the bounded harness, and pending fixture evidence is retained. It
executes no NFS service/export/mount or production configuration controls.

### Session rejection accepted; disposable container media policy

The user confirmed the expanded scope lab through `6306413`: both the later
controller interpreter and different network were rejected, and database bytes
were unchanged. No production/NFS configuration was changed.

The next container fixture checks a different prerequisite: a running read
service with writable application state and read-only media. The harness creates
only new labeled containers and marked media/state directories. It first proves
its disposable RW writer can change a fixed payload, stops that exact new
container, and starts a replacement with the same media bind mounted read-only.
The Python fixture service returns a synthetic keep signal and increments a
persistent application-state read counter. Separate client calls must observe
new responses while a single fixed media write fails specifically with EROFS;
permission/transport errors or a successful write do not count as acceptance.
Writes are never retried after uncertain outcomes.

The harness then explicitly restarts only its new read-only container and repeats
the API/write checks. Payload bytes must remain unchanged and the original RW
fixture container must remain stopped. Both containers have read-only root
filesystems, no external network, all capabilities dropped, no-new-privileges
and restart policy `no`; no Docker socket or production paths are mounted.
Cleanup removes only those new containers and retains fixture files. The cached
pinned Python image is used without pulling, installing packages or building.
The test can run on either existing shfs/native lab parent without an FS-name
allowlist or a rename fallback.

This is a synthetic HTTP service, not Jellyfin. It tests a Docker mount policy
and fixture read availability, not live protection freshness, NFS/cache denial,
complete overlapping production mounts or administrative exclusion. A Docker
administrator could start the stopped RW container or recreate an RW mount;
those routes still require independent maintenance controls. All reports keep
production authorization, restart inhibition and global writer exclusion false.
No existing application is stopped or reconfigured, and Gate 6 stays open.

### Accepted container fixture and advisory production-route review

The user confirmed `caf3317` on both lab parents. Read responses remained fresh,
media writes were denied before and after the new container restart, payload
bytes were unchanged and the original disposable writer remained stopped.

The next read-only host script enumerates existing containers before launching
its observer, then streams only selected state/mount/restart/admin fields into
a cached-image Python observer. The observer has no Docker socket, network,
capabilities or writable root/source mounts. No environment, command-line or
credential fields are requested. An end record is emitted only if every
selected inspect succeeds; incomplete/malformed/bounded-out input is blocked.

The analyzer marks source overlaps against all explicitly declared media roots
and nested writable destination overlaps, even when a parent media mount is
read-only. It keeps stopped containers in scope and reports administrative
socket access regardless of a socket mount's RW flag, privileged/capability/
device routes and writable non-bind mounts requiring review. An unrelated
lexical prefix is not silently treated as a physical alias. Conversely, absence
of a declared overlap never provides clearance: actual path resolution, hidden
aliases, host/share writers, administrative restart controls and snapshot
continuity remain unverified. These are review hints, not an enforcement plan
or authorization to stop/reconfigure any application.

For Tower, pass both `/mnt/user/media_storage` and `/mnt/media/media_storage` as
explicit declared roots. This acknowledges the known deployment aliases without
making them application defaults or assuming these are the only possible paths.
The script never changes services, exports, mounts, restart policies or media.

### Deployment review received

The `656679e` Tower report contains 22 observed containers and 11 review entries.
See [the control matrix](sqlite-container-maintenance-review.md) for the concrete
writer, nested-mount and administrative routes. The advisory analyzer now
separates required control categories and counts destination overlap only
between distinct mounts, retaining the original direct-media write warnings.
It does not turn generic cache-volume flags into confirmed media writers.
Dashboard availability is a pending design decision, not service-stop approval.
No repeat inventory is needed just for this classification correction.

### Dashboard design choice and private API-client pause fixture

Both dashboards may be temporarily unavailable during initial maintenance,
per the user's design choice. This does not authorize changing existing services.
See [the container control matrix](sqlite-container-maintenance-review.md) for
the new bounded Unix API-client pause/controller-death fixture. It uses a private
counter-only endpoint, not a real Docker socket, and preserves a paused client
until that endpoint is ended during cleanup. Explicit unpause/recreation,
Docker/host restart behavior and other administrative routes remain unverified;
no production writer-exclusion or restart permit is issued.

### Private API pause acceptance and kernel-client capability review

The user confirmed the `58d5ce8` private API pause/controller-death scenario on
Tower, retaining the paused client and action count one while the endpoint
remained live. No automatic restoration or real socket access was performed.

The NFSv4/kernel-client cache gap now requires the actual host kernel/client
capabilities. `sqlite_nfs_kernel_client_probe.sh` is read-only and executes no
mount/NFS helper or module-load operation. It reports registrations separately
from availability of configuration/parameters; missing sysfs/config observations
cannot be promoted to a disabled-feature claim. It hashes an available mount
helper without running it and selects only NFS-related kernel-config booleans.
No credentials, general configuration or mount options are dumped.

The upstream [Linux LOCALIO documentation](https://docs.kernel.org/filesystems/nfs/localio.html)
explains that same-host clients can bypass network RPC for read/write/commit
and that `localio_enabled` is a module-level control. Current upstream docs are
not proof of Tower's kernel implementation. The probe never writes that global
setting. Kernel-client mounts, cache recovery, bounded teardown and LOCALIO
behavior require a reviewed fixture suited to the observed build; they are not
accepted from raw-RPC tests or version strings alone. Production activation,
writer exclusion and restart inhibition remain false.

### Tower kernel prerequisite result and module metadata review

The user confirmed kernel `6.18.54-Unraid` with nfsd registered and nfs/nfs4 not
registered, mount helper present and LOCALIO/config observations unavailable.
Client-module availability remains unknown. The extended read-only probe uses
`modinfo -k` for that running release and selects only module filename, vermagic,
depends and LOCALIO parameter types. It does not invoke a module loader or
source loader configuration, and no global kernel parameter changes are made.
See the [unexecuted kernel-client fixture plan](sqlite-kernel-client-test-plan.md)
for the prerequisites and write/cache/teardown evidence needed before a mount
fixture is chosen. Gate 6 and all production denials remain unchanged.
