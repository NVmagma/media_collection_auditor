# NFS host fence: candidate change package

Status: design draft pending administrative trust decision and implementation.
Not an installer, approved procedure or permission to change Tower. No production
SQLite activation, deletion, NFS configuration change or service control is added.

## Confirmed startup constraint

The previously reviewed pinned startup source hashes were downloaded again and
match Tower's supplied fingerprints. `rc.inet2` leaves NFS startup to emhttpd;
`rc.local` installs plugins before management startup in normal mode, but skips
packages/plugins in Safe Mode. It selects `go.safemode` there and has a direct
management fallback. A plugin-only or ordinary-go-only guard cannot establish
all-mode coverage. The rc.S testing hook is conditional and is not a general
supported deployment hook for this host version.

Sources at revision `26eb1b5c1d547ddbf44a38e63956ba24f659098b`:
[rc.inet2](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/etc/rc.d/rc.inet2),
[rc.local](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/etc/rc.d/rc.local),
[rc.S](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/etc/rc.d/rc.S).

## Administrative boundary must be explicit

The candidate is conditional on trusted host administrators following the
maintenance protocol. It does not protect against root intentionally replacing
guards, enabling services through unreviewed routes, altering boot configuration
or accessing native runtime sockets. This is separate from ordinary NFS clients,
container writers and automated starts, which require real technical controls.
The operator's design choice is pending; it is not inferred from root-owned
socket metadata or prior permission to pause shares.

If hostile/overriding host administrators must also be excluded, do not deploy
this application-level model as adequate. A different host security/control
architecture would be required. No callback, checkbox or repeated observation
can substitute for that architecture.

## Candidate layers and exact change classes

| Layer | Candidate change | Required verification and rollback evidence |
| --- | --- | --- |
| Persistent NFS opt-out | Use a reviewed supported Unraid settings operation to disable NFS before maintenance; preserve the original preference | Fresh persistent and manager-observed state, independently stopped NFSD and export inventory; original config backup/digest; no raw edit of the live manager state file |
| Current-boot dispatch fence | Install the reviewed deny-only guard at both rc.nfsd aliases, without stopping management | Both aliases resolve to expected guard bytes/mounts, all reviewed restart/settings routes deny, management remains usable; retain original script identities and exact owned mounts |
| Durable unresolved request | Store deny/recovery state outside exported media/appdata paths before external actions | Private control storage and aliases reviewed; request survives controller death; no implicit deletion, expiry or repair |
| Reboot recovery | Retain persistent NFS opt-out while the request is unresolved; re-establish runtime guards before any new work | Normal and Safe Mode acceptance with real boot/manager behavior, source/config compatibility checks and no automatic NFS re-enable; do not infer this from Ubuntu guest boots |
| Explicit restoration | Separate reviewed recovery after accepted outcomes/client clearance | Compare original/current configuration; refuse to overwrite intervening changes; restore only owned changes; no automatic restoration after failure |

Persistent disable is a candidate to avoid relying on a plugin in Safe Mode;
it has not been accepted as a complete fence. It does not itself prevent a
privileged explicit start and does not clear queued client writes. The reviewed
settings operation, actual manager behavior and restart coverage must all be
implemented and tested before installation is proposed.

## Entry sequence to implement

1. Verify compatible startup/control sources, complete writer/alias scope and
   available recovery access. Refuse unknown state before applying anything.
2. Save original configuration and create/fsync the unresolved request before
   any service or preference change. An uncertain change retains the request.
3. Establish persistent opt-out and current-boot restart inhibition using the
   reviewed adapter. Keep management available. Independently verify effects;
   command success and zero NFSD threads alone are insufficient.
4. Resolve pending client writes before collecting any authoritative baseline.
   Unknown writeback latches the durable deny hold. No automatic clearance from
   a later successful fsync/unmount.
5. Join NFS, Docker and host/storage bindings in the unified controller. Missing
   or lost binding blocks work; media operations never use this draft as a permit.
6. Rehearse controller death, uncertain commands, restart attempts, normal/Safe
   Mode boot, mismatched sources/configuration and failed restoration. Preserve
   originals and every uncertain record. Test availability and recovery separately.

## Still absent before requesting installation approval

- Reviewed Unraid settings-operation adapter and safe configuration backup/CAS;
- actual persistent/runtime NFS fence installer with exact changed-file/mount
  manifest, compatibility checks and a manual rollback/recovery implementation;
- independent Unraid boot-mode and management availability acceptance;
- complete host/storage ownership and source-entry verification integration.

No production action is requested from this draft. Do not experiment on Tower
simply to discover whether the proposed layers work. The separate Linux VM can
rehearse mechanisms, but cannot stand in for Unraid boot/manager acceptance.
