# Gate 6: host implementation and acceptance package

Status: design review; **not approved for installation or execution**. No host
setting, service, kernel control or production media operation is changed by
this document. JSON remains authoritative. SQLite activation, filesystem deletion
and automatic writer restoration remain disabled.

This is the current remaining-work checklist. The chronological evidence is in
[Gate 6 closure](sqlite-gate6-closure.md). A passing guest rehearsal must not
remove a production blocker from `sqlite_production_cutover_guard.py`.

## Accepted evidence and its limits

| Item | Accepted result | Limit |
| --- | --- | --- |
| Live Docker observer | Selected full IDs, active policy, stopped/restart-disabled writers; failure latches | Not complete host inventory, prior stream revocation or an Unraid installer |
| Live NFS observer | Empty kernel exports, zero threads, disabled fixture preferences, read-only dispatch guard mounts | Private fixture paths/settings; not actual Unraid startup enforcement |
| Live storage observer | Bound root/stage descriptors and mount namespace; same-inode overlays and mount detachment reject | Detects changes; does not enforce continuous exclusive ownership |
| Combined real copy | Healthy copy and four storage-loss boundaries; originals retained, retry/release denied | Synthetic collection and maintenance fence setup; no production permit |
| Replacement controller and real reboot | All four retained attempts reject their precise scope change despite healthy fresh observations; bytes unchanged | Explicitly prepared new fixtures; not automatic host restart inhibition |
| Real clients and protections | Mac v3 and guest v4 delayed-write recovery; real Jellyfin read-only protection reads | Recovered clients do not automatically clear the durable uncertainty hold |

## Initial operating model decision

Unraid web management and SSH must remain available. Human root administrators
are trusted to follow the maintenance protocol; automated privileged starts still
need technical fencing. No kernel module changes on Tower are required by the
proposed host model.

Two Docker designs have different remaining costs:

| Design | Disruption | Implementation still needed |
| --- | --- | --- |
| Selected writers with live Docker | Relevant writers/dashboards pause; unrelated services may remain up | Host authorization service and its startup ordering, prior streams/runtime routes, durable hold, Unraid daemon integration and recovery |
| Entire Docker service offline | Every container pauses, including AdGuard DNS and unrelated services | Supported persistent Docker opt-out, verified daemon/runtime/container shutdown, current-boot dispatch guards and normal/Safe Mode acceptance |

The user accepted the second design: all Docker services may pause during the
initial maintenance window, including AdGuard DNS. This is a design decision,
not permission to stop Docker or proof of a fence. The selected-writer live
Docker design is no longer required for that initial window.
A disabled preference alone is insufficient: the reviewed `rc.docker start`
dispatch can directly launch the daemon. The direct/manual privileged bypass
boundary remains the accepted trusted-administrator protocol, not an assertion
that UID 0 is always trusted.

## Remaining implementation deliverables

1. **Runnable host controller.** Establish a reviewed runtime that remains alive
   with the worker paused (and with Docker offline if that design is selected).
   Tower has no host Python installation; earlier Python tests ran in containers.
   Tower accepted the disposable cached-image export/chroot runtime with Python
   3.12.15 and SQLite 3.46.1, avoiding a host Python installation. Application
   packaging and actual host bindings still require implementation and review.
   Bind a single durable private request, exact scope and exclusive controller
   lock before any external action. Confirm the control path is outside every
   exported/bind alias; no hard-coded Unraid pool or filesystem name is adequate.
2. **Actual Unraid fence and recovery implementation.** Use supported settings
   operations for persistent opt-out. The compiled manager handlers are not
   established by public form source, so an initially approved administrator UI
   step is preferable to an invented HTTP POST or editing runtime `var.ini`.
   Implement current-boot dispatch inhibition, exact source compatibility checks,
   independently verified stopped state and owned-change records. Keep emhttp,
   management sockets and SSH available. Account for automated host writers and
   alternate/inherited runtime access; incomplete scope denies admission.
3. **Production ownership/verifier connection.** Bind the actual operation's
   source, destination, state and all aliases to the enforced boundary. Consume
   that live binding in the source-entry action, fresh protection collection and
   atomic completion path. Matching inode/hash or repeated observations alone
   cannot supply it. Preserve originals and uncertain intents; no deletion.
4. **Explicit recovery.** Provide exact original/candidate hashes and changed
   file/mount/service inventory. Restore only owned, unchanged artifacts; refuse
   intervening edits or uncertain outcomes. Neither a reboot, healthy observer,
   no pending media intent nor a successful later fsync clears maintenance.
   Recovery must be available through SSH/local console while management stays up.

These are absent deliverables, not work already completed by the guest scripts.
A host package is ready for installation approval only when all four are concrete
and its scoped changes, backups and rollback can be reviewed together.

## Finite acceptance sequence after implementation

| Acceptance | Required outcome |
| --- | --- |
| Separate Linux mechanism rehearsal | Exact installer/recovery code, partial installation and command failures preserve the deny request and originals; no automatic restoration |
| Unraid compatibility review | Supported version/source identities, controller runtime, actual scope/aliases and private control storage verified; unknown state blocks |
| Approved Tower maintenance entry, without production moves | Persistent opt-out plus runtime controls established; management/SSH usable; clients accounted for; all required fresh bindings available |
| Controller death and attempted automatic restart | Durable request remains; ordinary clients and reviewed automated writer routes cannot write/restart; fresh controller cannot adopt the attempt |
| Approved normal and Safe Mode boot acceptance | No writer startup while unresolved; management/SSH available; boot mismatch remains blocked; never infer this from an Ubuntu boot |
| Reviewed restoration of the disposable maintenance exercise | Only exact owned changes restored after explicit review; conflicts/unknown outcomes retain the fence; original production state/media unchanged |

The two Tower boot-mode checks are disruptive acceptance work and require a
separately scheduled, explicitly approved window. They are not commands to run
now. Disposable source/destination data is required before any actual move
acceptance. Production lifecycle activation remains a separate later approval.

## Closure rule

Gate 6 stays open until the actual host implementation, ownership-bound verifier
and integrated failure/boot recovery requirements above are accepted. Code-only
preparation and guest tests cannot truthfully close it. Gates 7–10 retain their
existing dependencies; no blocker is waived to make the gate table green.

## Confirmed additional host routes and protection dependency

The operator accepted pausing SMB and scheduled mover activity in the same
maintenance window. Tower's Samba and both mover-script hashes match the pinned
Unraid revision; the move-helper binary/environment and existing children still
need scope verification. The current read-only preference probe also corrects
CRLF/unquoted-format observation while rejecting ambiguity. See the
[SMB/mover review](sqlite-smb-mover-source-review.md).

Fully stopping Docker also stops the existing Jellyfin protection API. Media work
therefore requires an independently reviewed, authoritative fresh-protection
provider or an execution mode that preserves that capability under the complete
fence. Offline preparation/recovery alone does not supply it. Cached pre-stop
observations cannot be promoted to trusted protection evidence. This requirement
must be solved before production move wiring; the permission to pause services
does not waive it. No production cutover blocker is removed by these design choices.

## Controller/recovery component progress

The disposable installer now persists per-route request-bound receipts and the
recovery entry point coordinates with its existing controller lock. Complete and
partial real Linux controller-death acceptance passes, including rejection of an
identical replacement guard using a unique mount identity. See
[controller/recovery integration](sqlite-dispatch-controller-recovery.md).
This completes the evidence handoff component only. Hidden-original verification,
actionable restoration and the actual Unraid host package remain required; none
of the four production deliverables above is declared complete by this fixture.

## Storage auto-start requirement and boot source review

The operator declined leaving the array/managed pools stopped after a maintenance
reboot. Preserve automatic storage startup, web management and SSH. The pinned
startup review confirms cron and Samba precede rc.local, and udev is not a
fail-closed barrier. No late-hook installer is claimed as complete enforcement.
Exact disposable SMB/NFS/mover persistent opt-out review artifacts are prepared;
actual settings application and normal/Safe Mode enforcement remain unimplemented.
See [boot enforcement review](sqlite-unraid-boot-enforcement-review.md).

## Runnable host preparation core

A stdlib-only preparation core and hash-verified bundle now retain a private
request under an exclusive lock, validate boot/namespace/directory/mount bindings,
and provide non-adopting review after interruption. The actual packaged entry
point passed Linux/Python 3.12.15 SIGKILL and competing-controller acceptance with
all external-action flags false. See
[host controller preparation](sqlite-host-controller-preparation.md).
Production runtime/control-location binding and service adapters remain unverified; this
component does not satisfy the complete runnable production-controller deliverable.

## Native launcher mechanism

A native preparation-only launcher now avoids the need for host Python, chroot or
new host mounts by invoking the copied interpreter with its own loader/libraries.
Local ARM64 Linux acceptance passed, including actual controller death and
non-adopting review. Tower/x86-64 native preparation and separate non-adopting
review also passed; its retained request stayed unchanged. The narrow lab
procedure is in [native launcher review](sqlite-host-controller-native-launcher.md).
No production control location, service adapter or boot enforcement is approved
by this mechanism. All controller/cutover authority blockers remain.

## Private location exposure review

`app/sqlite_control_location_review.py` now checks detached candidate paths and
explicit aliases against observed NFS export roots, SMB share roots and container
bind sources. Both parent exposure and nested exposure conflict; a read-only
container bind also exposes controller state. Component boundaries prevent an
`appdata` export from incorrectly matching an unrelated `appdata-private` sibling.
Ambiguous paths and malformed observations are rejected rather than normalized.

This helper performs no filesystem or service operations. Even an empty conflict
list retains blockers for incomplete alias/exposure coverage and unverified live
identity, permissions and durability. It is not connected to controller authority
and cannot clear the private-location blocker. Actual host inventory collection,
private path selection and live binding still remain to be implemented/reviewed.
