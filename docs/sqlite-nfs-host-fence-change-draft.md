# NFS host fence: candidate change package

Status: administrator trust model accepted; host implementation remains a draft.
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

The user accepted trusted host administrators following the maintenance
protocol as the initial design boundary. It does not protect against root intentionally replacing
guards, enabling services through unreviewed routes, altering boot configuration
or accessing native runtime sockets. This is separate from ordinary NFS clients,
container writers and automated starts, which require real technical controls.
This decision does not authorize any Tower changes. It is not inferred from
socket ownership or previous permission to pause shares. Automated root processes
and privileged containers are still required control routes; UID 0 alone does
not make a process a trusted administrator.

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


## Exact configuration candidates prepared

`app/sqlite_nfs_config_candidate.py` now produces disabled-NFS preference bytes
without applying them. Exactly one canonical yes/no assignment is required;
quoted/unquoted forms and existing line endings are preserved. Missing, duplicate,
ambiguous or executable preference values block. All unrelated bytes remain
unchanged. Restoration candidates require the exact original-to-disabled
transformation and byte-for-byte unchanged current content, so unrelated external
edits cannot be overwritten. The comparison is not an atomic file replacement or
permission to restore NFS.

`app/sqlite_disposable_nfs_config_plan.py` stores exclusive 0600 before/candidate
artifacts and a manifest in a new 0700 plan directory beneath a marked disposable
root. It reads only the lab's share.cfg, never the host's settings. Source,
marker, plan-directory and artifact bindings/content are checked; symlinks,
hard links, FIFOs, drift and existing plans refuse success. Partial artifacts stay
available for review; source bytes are never written. Files and directories are
fsynced, but no claim of host power-loss acceptance is made.

The synthetic CLI `scripts/sqlite_nfs_config_plan_lab.py` creates a new lab with
fixed fake settings and prepares that package. Local acceptance: 87 focused
checks passed with six existing platform skips; the actual synthetic CLI retained
its source and generated its private review artifacts. Output exposes no raw
configuration, shell commands or credentials. All application/restoration,
production and ownership authority flags remain false.

This implements backup/candidate preparation only. The supported Unraid settings
operation, held-binding atomic application/recovery, runtime service fence and
all-mode boot acceptance remain required. No raw edit of var.ini or share.cfg,
service stop/reload, plugin installation or Tower test is requested by this step.

## Global settings operation boundary confirmed

The pinned [NFS management page](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/emhttp/plugins/dynamix/NFS.page)
has separate global enable and protocol/thread forms. The global preference uses
the manager's `/update.htm` handler. The reviewed `nfsSettings apply` helper only
writes protocol/thread settings and conditionally restarts an already-running
service; it is not a substitute for globally disabling NFS.

No public page source establishes the compiled manager handler's full transaction,
CSRF/authentication or failure semantics. Do not synthesize a privileged POST,
source shell configuration or edit the live manager state as a shortcut. The
initial package should use an explicit approved administrator settings step until
that integration has its own accepted adapter. Normal/Safe Mode startup and live
manager behavior still need actual Unraid acceptance. No setting is changed by
reading this draft or running the observer below.

## Live NFS observation backend accepted in the separate VM

`app/sqlite_disposable_nfs_backend.py` now reads actual Linux boot/network/mount
scope, zero NFSD threads and empty kernel exports. It additionally requires both
marked-fixture preferences explicitly disabled, both guard files matching an
explicit digest, and exact read-only/nosuid/nodev bind-mount entries. Root, marker,
preferences, guard identities and mount IDs remain bound and are sampled again.
Any change, error or interruption latches that observer failed. It does not start,
stop, export, install, restore or clear anything and returns no ownership permit.

The reproducible `scripts/sqlite_nfs_backend_guest_lab.py` runs only in the dedicated
separate VM, under a fresh private mount namespace. It refuses a running/exporting
NFS baseline rather than stopping it. Package services were explicitly stopped in
that disposable VM before rehearsal. It mounts only new fixture targets; all 12
fixed dispatch attempts returned the reviewed denial. A controlled read-write
remount was rejected, and remounting read-only did not revive the failed observer.
Real guest kernel state and mountinfo were used, not caller-provided receipts.

The private targets are not Unraid's live rc.nfsd aliases, and the preferences are
synthetic lab files. Therefore this is backend/mechanism acceptance, not host
installation, complete NFS restart inhibition, writeback clearance or proof of
production boot coverage. The existing durable client-writeback hold remains
separate and authoritative. The unified controller still needs the real host
installer/setting operation and complete host/storage ownership binding.

Validation for this backend increment: 96 focused local checks passed with six
existing macOS capability skips. The private guest rehearsal passed with actual
mountinfo/kernel observations. Fixture evidence was archived and the separate VM
powered off. Tower was never contacted; no host setting or service was changed.
