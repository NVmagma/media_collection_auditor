# Initial production ownership model: operator-controlled maintenance window

The user confirmed that shares or host jobs can write to the media folders and
accepted a maintenance window as the initial design requirement. This is not
permission to stop services, disable exports/jobs, remount storage, update an
image, activate SQLite or delete media. Production remains JSON-authoritative.
Gate 6 is open; no ownership enforcer is implemented or approved yet.

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
