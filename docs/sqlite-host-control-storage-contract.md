# Production host control storage contract

Status: design requirements; no storage adapter or installation is implemented.
No location described here is approved for production. This document does not
remove a controller or cutover blocker.

## Accepted Tower observations

On 2026-10-24 the operator supplied the completed ancestor snapshot:

| Path | Owner | Mode | Role |
| --- | --- | --- | --- |
| `/` | 0:0 | 0755 | Host root |
| `/mnt` | 0:0 | 0755 | Host mount parent |
| `/mnt/media` | 99:100 | 0777 | Native pool root |
| `/mnt/media/sql_test` | 0:0 | 0777 | Disposable lab parent |
| `/mnt/user` | 99:100 | 0777 | User-share root |
| `/mnt/user/sql_test` | 0:0 | 0777 | Disposable lab parent |

The native and user-share routes are separate observed devices. Their intended
relationship does not prove complete alias coverage. Earlier export/bind inventory
showed no direct lexical overlap with `sql_test`; effective SMB/custom exports and
all backing aliases remain unverified. Root-owned lab entries are still writable
by other users under these mode bits. The snapshot establishes a design constraint,
not an exploit test or a live ownership attestation.

## Required properties

The retained request and recovery history must survive controller death, Docker
shutdown and host reboot. A directory on the host's volatile root filesystem
cannot alone provide that retention. Runtime availability and durable control
state are separate requirements: the copied Python runtime passing its launch
check does not establish either storage privacy or recovery authority.

A production adapter must establish all of these properties before persisting an
authoritative request:

- A durable backing location with supported flush/locking behavior, checked by
  capability rather than a filesystem-name allowlist.
- Exclusive controller ownership, private file permissions and bounded,
  no-follow access to each artifact.
- A stable entry-point chain whose mutable components cannot be replaced by an
  untrusted writer. A 0700 leaf alone cannot establish this on the observed paths.
- No untrusted exposure through native paths, user-share aliases, SMB/NFS roots,
  container binds, named-volume backings or alternate mount routes. Read-only
  exposure also matters because control state is private.
- An independently retained pending-maintenance indication available to boot
  enforcement before automated writers can resume. Loss of the control store
  while maintenance is pending must block writers rather than create a new request.
- Read-only recovery that checks the exact retained store and history. A missing,
  replaced, partially written or ambiguous store never implies maintenance ended.

The controller must hold directory/lock references and recheck identity around
sensitive transitions. These checks detect some replacement races; they do not
turn an untrusted writable parent into a private durable store. After reboot,
current-boot scope changes require explicit recovery, not automatic adoption.

## Storage design boundary

A separately mounted persistent control store beneath a root-controlled host
parent is a candidate design, not a completed solution. Its backing path or image,
mount source, alternative aliases, startup ordering and unavailable-store behavior
must satisfy the same requirements. Adding a bind mount to the current lab tree
would not by itself establish them. A root-owned mount target is not evidence that
its backing storage is inaccessible elsewhere.

Implementation must preserve the user's requirements: storage starts automatically;
Unraid management and SSH remain available; ordinary automated writers remain
fenced while maintenance is pending. No boot hook, privileged mount operation,
new volume/image or storage-permission change is authorized by this design.

Do not chmod/chown the pool root, user-share root or existing lab parents as an
automatic fix. Do not move the journal into media/appdata, use volatile-only state,
or treat an empty exposure inventory as private-store approval.

## Next implementation boundary

Resolve durable backing and boot-time availability together with the boot writer
fence. The storage adapter needs a verified source identity and an independent
pending-state anchor; boot enforcement needs a fail-closed response when that
source is missing or replaced. Until those are implemented and tested together,
the preparation controller remains observation-only and retains
`private_host_control_location_unverified`.

Further ancestor snapshots of these same lab paths are unnecessary unless their
configuration changes. Subsequent acceptance should test a concrete disposable
storage/boot adapter, including backing replacement, missing storage, controller
death and reboot-scope recovery, before proposing production installation.
