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
