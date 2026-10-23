# Unified maintenance controller: implementation contract

Status: reviewable design and disposable integration foundation, not an installer,
production adapter or ownership permit. JSON remains authoritative. Production
SQLite activation, filesystem deletion and automatic writer restoration stay off.

## Controller placement

Use a host-side controller outside the current auditor worker. The auditor itself
has a writable media bind and must be covered as a writer. Its DRY_RUN setting and
read-only integration API do not establish filesystem/state exclusivity. The
controller must not require that worker or its HTTP API to remain alive to retain
a fence or preserve recovery evidence.

Unraid web management must stay available. Docker control actions may be denied
explicitly during maintenance; emhttp and its shared management socket are not
Docker API targets. The guest systemd dependency proof is component evidence,
not a mechanism for installing startup guards on Unraid.

## One durable request, three independent control domains

The existing boot/session-bound maintenance journal supplies the disposable
coordination skeleton. The production counterpart needs durable state before
any external action, a single active controller, recorded exact scope, and no
adoption/replay of uncertain actions after controller death.

| Domain | Required implementation binding | Current component evidence |
| --- | --- | --- |
| Docker | Exact fresh full IDs; relevant media/control mounts and privileged routes; active AuthZ policy and disabled restart/stopped state; prior streams and native runtime access accounted for | Actual selected-writer stop/restart, policy loss, guest boot/corrupt-hold and copy-action checks |
| NFS/shares | Reviewed real service/startup fence; actual export/client scope and pending-write handling; no automatic clearance from server thread count or a recovered fsync | Mac v3 and guest v4.1/v4.2 recovery; real uncertain client latches the copy-denying hold |
| Host and storage | Reviewed jobs/admin access; resolved operation-specific source/destination aliases, held directory/mount/database identities and source-entry ownership | Disposable identity/retention checks; host/container snapshots are advisory only |

A positive result from one domain cannot substitute for another. No host backend
may silently fall back to a synthetic receipt, callback boolean, operator flag,
matching hash or cached observation. Missing backend/unknown scope must block
before an authoritative media baseline or action. Trusted host administration
must be explicitly scoped in the eventual installation review; the design cannot
claim protection against arbitrary root reconfiguration. Root-owned 0700 runtime
directories restrict ordinary path access but do not prove absence of bind aliases,
elevated clients or inherited connections.

## Ordering to preserve

1. Persist the maintenance request and exact intended scope before service/API
   changes. Partial or uncertain external outcomes retain that request.
2. Establish each required real fence and verify continuity. For Docker, reduce
   restart policy and stop selected writers under the active control boundary;
   never infer quiescence solely from successful stop responses or restart=no.
3. Account for NFS queued writes before collecting a media baseline. Unknown
   writeback latches the durable deny hold. Explicit client recovery does not
   clear it or authorize media work by itself.
4. Enter work scope only when every required backend supplies its accepted live
   binding. Hold media/journal locks throughout the one-shot operation. Recheck
   those local bindings and the hold after external observation returns, before
   any local checkpoint or media action. Rechecking is not continuous ownership;
   the actual exclusion controls must cover intervals between observations.
5. Bind one exact operation before collection; refresh protections and verify
   source/copy identities at the existing action boundaries. Source originals
   stay retained; deletion is never part of this controller's initial scope.
6. If any boundary is lost, stop further actions, retain every available original,
   copy and pending record, and leave maintenance unresolved. A media commit can
   precede the maintenance outcome checkpoint. No pending intent is not proof of
   successful completion and never authorizes a retry.
7. Record independently verified outcomes only while the full boundary remains
   valid. Production writer release requires its separately accepted explicit
   recovery protocol. No expiry, startup hook or controller restart reopens writers.

## Production implementation still required

The current Python protocols and guest launchers do not implement the complete
three-domain ownership boundary. In particular, the following must be concrete
before proposing Tower installation:

- Unraid startup integration ordered before legitimate writer/NFS startup, plus
  persistent deny-state recovery and preserved management availability;
- scope-specific Docker/host/runtime access coverage and existing-stream treatment;
- production NFS dispatch/restart inhibition and accepted writeback clearance;
- a verifier consuming those real bindings for safe source-entry action and
  coherent recovery, without treating point-in-time observations as a fence;
- an exact file/service change manifest, backups, manual recovery/rollback and
  failure rehearsal package, followed by explicit installation approval.

There is no production install, startup edit, socket permission change or service
control in this contract. No gate is marked complete from these design choices.

## Required-domain disposable admission implementation

`app/sqlite_unified_disposable_controller.py` now supplies one admission wrapper
for the marked disposable copy flow. It requires callable Docker, NFS and
host/storage adapters; a caller cannot replace the combined checker with the old
single observer argument. No host backend or installer is provided by this wrapper.

The combined checker in `app/sqlite_disposable_boundary_set.py` samples all three
domains and revisits them in reverse order. Each adapter must return None or raise;
booleans and receipt objects deny rather than act as authority. A reversed/invalid
clock or a completed observation sequence exceeding five seconds denies. Backend
calls must still have their own bounded I/O: the elapsed-time check does not
interrupt a hung callback. Failure, interruption, concurrency or recursive use
latches that checker instance closed. It never automatically resumes after an
adapter later returns a good result and it returns no permit or receipt.

This latch is in-memory, not new durable ownership evidence. Existing one-shot
journal/session and writeback-hold checks remain authoritative and are neither
cleared nor replaced. A fresh checker or no-op fixture adapter cannot establish
production ownership; production paths remain unwired, and release, production
and complete writer-exclusion flags remain false. Repeated observations do not
close the interval requiring an actual enforced fence.

Local integration checks confirm that failure of any one domain blocks the real
disposable journal/media wrapper before collection and attempt creation, preserving
source state. Other tests cover missing adapters, second-pass drift, receipt
rejection, clock reversal/expiry, interruption and recursive use. These use
synthetic adapters and are not new host-enforcement acceptance.

## Extracted live Docker observation backend

`held_disposable_docker_observer` in `app/sqlite_disposable_docker_backend.py` is
now a real read-only Engine adapter for a marked disposable daemon. The caller
supplies an expected daemon ID, exact configured fixture policy name and nonempty
full selected-ID scope. It binds the canonical fixture directory, regular single-
link marker and existing Unix socket inode, then rechecks those bindings before
and after API reads. A replacement socket is never automatically adopted.

Each observation requires the expected daemon ID, live restore explicitly false,
the exact expected fixture authorization chain and strict stopped/restart-disabled
state for every selected container. Responses are size bounded, duplicate JSON
keys deny, each read has a timeout and the sequence has a five-second elapsed
budget. Network/parse uncertainty is redacted and latches the observer failed;
policy reload does not reset that failed observer. It returns no permit and
performs no Docker mutation or service control.

The guest copy launcher now uses this adapter instead of its embedded checks.
Independent Engine 29.8.2 acceptance verified healthy selected state, real copy
completion with retained originals, unknown selected-ID denial, policy-death
denial and a retained failed observer after explicit deny-policy reload. Synthetic
media bytes remained unchanged except the intended disposable copy artifacts.
98 focused local regressions passed with six existing platform skips. Socket
binding tests ran outside the local sandbox's bind restriction. Guest evidence
was retained and the VM powered off; Tower was not accessed or changed.

This is the Docker observation side of an already established fixture fence, not
a complete production backend. Caller-selected IDs do not prove inventory
completeness, repeated snapshots do not enforce continuity, and the marker does
not protect against privileged redirection. Production policy installation,
control-route scope, NFS startup/restart inhibition and real host/storage ownership
remain required. Existing production activation and release guards are unchanged.


## Accepted administrator scope

The user accepted trusted host root/Unraid administrators following maintenance
rules until explicit recovery. This narrows the adversarial boundary; it does
not authorize installation or excuse automated root writers, privileged container
routes, client access or accidental service restarts from technical fencing.
There is no runtime ignore-root switch, and this model must not be advertised as
protection against an administrator deliberately replacing its controls.

### Disposable storage observations

`held_disposable_storage_observer` holds descriptors for the marked media root
and its four stage directories. Fresh opens must retain their device, inode and
Linux mount ID, and the mount namespace and disposable marker must remain bound.
It can supply the required `host_storage` callback. Different stage mounts and
filesystem types are allowed; this adds no filesystem allowlist.

The observer does not acquire the runner lock (the copy wrapper already owns
that lock), freeze directory contents, enumerate host writers or establish a
restart fence. Sampling detects drift; it cannot prove continuous exclusion.
Any failure latches the instance, and a callback retained after context closure
rejects use. The actual SQLite identity and transaction checks remain in the copy
wrapper. No production adapter or release permit is introduced.

`python -B -m scripts.sqlite_storage_backend_guest_lab --root NEW_ABSOLUTE_PATH`
is a separate-VM rehearsal, guarded by the dedicated guest identity check. It
creates a private mount namespace and new synthetic paths. It accepts an initial
stage bind mount, rejects a second bind overlay with unchanged device/inode but
a different mount ID, checks the combined required-domain callback rejection,
and rejects baseline mount detachment. A held baseline descriptor makes ordinary
unmount busy, so that specific fixture loss uses lazy detachment of its newly
created private mount. Namespace exit removes remaining fixture mounts. No host
service, exports, kernel modules or production paths are controlled.

### Combined live-observer copy rehearsal

`scripts/sqlite_unified_copy_guest_lab.py` connects the selected private Docker
writer observer, the live NFS fixture observer and the live storage observer to
the actual maintenance-bound disposable copy. The Docker fixture must already be
fenced and running on its private socket. The script never starts/stops that
daemon or changes its policy. It requires its new root beneath the private
writer's media directory, checks the selected writer before creating NFS mount
fixtures, and runs inside a private mount namespace of the dedicated Linux VM.
The NFS server must already be stopped with no exports. Dispatch guards cover
new fixture paths, not real Unraid service entrypoints.

The independent VM accepted the healthy copy, then rejected same-inode stage
mount overlays at collection, publication, source quarantine and final completion.
Originals and attempt evidence were retained, retries changed no retained bytes,
and automatic release stayed disabled. The final case includes an already
committed SQLite media checkpoint: that checkpoint alone is not accepted as a
verified maintenance outcome after boundary loss. No external Jellyfin/Arr
collection was performed. These observations still do not establish complete
host writer coverage, real Unraid startup fencing or production ownership.

The storage-only variant is `scripts/sqlite_storage_copy_guest_lab.py`. Passing
only one external domain adapter rejects before fixture creation; passing both
uses the required-domain composer. Every checkpoint creates an independent
fixture and observer; an earlier failed instance is never reset or reused.
