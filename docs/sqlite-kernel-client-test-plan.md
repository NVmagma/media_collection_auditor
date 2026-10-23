# Kernel NFS client fixture prerequisites and test boundaries

This is an unexecuted fixture design, not a module-load/mount command or a
production enforcement adapter. Gate 6 remains open. Production authority is
JSON; activation, deletion and clearance remain disabled.

## Execution deferred on Tower — October 22, 2026

The user raised the risk of exercising kernel clients on the production host.
Live client-module loading and kernel-client mounts are deferred on Tower.
Private namespaces share the host kernel and are not a separate failure domain.
Do not resume these operations as the automatic next step after a passing probe.
Continue local and disposable work that does not require those operations.

The extended metadata report found matching-release nfs/nfsv4 module files;
LOCALIO capability remains unknown. No client module load or kernel-client mount
was performed by these probes. The cached-write/retry/recovery acceptance gap
remains open: this deferral does not close Gate 6, authorize moves or weaken any
production blocker. Revisit execution in a separate suitable environment or
review an alternative ownership design before claiming production exclusion.

## Tower evidence received

The `83b7b7e` probe observed kernel `6.18.54-Unraid`, registered `nfsd`, and no
registered `nfs`/`nfs4` filesystems. The mount helper exists, but active LOCALIO
parameters and embedded kernel configuration were unavailable. No module was
loaded and no mount performed. These observations do not distinguish an
available unloaded client module from missing client support.

The extended probe queries `modinfo` for `nfs`, `nfsv4` and `nfslocalio`, scoped
to the observed running release. It reads only filename, vermagic, dependency
names and the two selected LOCALIO parameter types. Module files in that release's
module tree may be hashed; other paths are not treated as verified module files.
It never uses modprobe/insmod, executes a mount helper, or evaluates module-loader
configuration. Missing fields are retained as unavailable/unverified. Metadata
matches cannot grant cache/fence acceptance or production clearance.

## Proposed stages requiring review before execution

1. **Client capability:** review installed-module identity/dependencies for the
   running kernel. Any future module load changes shared host-kernel capability,
   even when subsequent mounts use private namespaces. Record existing module/
   parameter/host-NFSD observations first. No automatic dependency unload or
   global LOCALIO parameter change is an acceptable cleanup shortcut.
2. **Private server/client setup:** only newly created marked export data and
   held private namespace/control references. No production exports, paths,
   service helpers or RPC state. Review the actual kernel's LOCALIO, NFSv4
   state/grace and bounded client failure/teardown behavior before selecting
   mount options. Unknown capability must block the test, not trigger an
   implicit load, protocol fallback or a production mount.
3. **Buffered-write evidence:** keep an existing client descriptor, record a
   successful baseline, and distinguish write return, fsync/commit outcome and
   independently observed server bytes. During a pause, an accepted buffered
   write is uncertainty; an RPC timeout is also uncertainty. Neither can clear
   intent or prove durable write denial. Kernel background retries are separate
   from application retries and cannot be reported as zero by assumption.
4. **Recovery/teardown:** review client quiescence, delayed writes and bounded
   cleanup independently of application process exit. A private restart may
   cause old buffered data to reach the fixture; preserve and report it. No
   automatic replay, intent clearing, production restoration or host repair.
   If teardown cannot be bounded for this environment, retain this acceptance
   gap rather than using production resources as a substitute.

A same-host kernel fixture may use LOCALIO. It must identify the actual path
and avoid presenting direct local IO as network-RPC denial. Changing the global
module parameter to obtain a desired test result is not part of this plan.

References reviewed for the design:
[upstream modinfo manual](https://man7.org/linux/man-pages/man8/modinfo.8.html),
[Linux v6.18 NFS client configuration](https://github.com/torvalds/linux/blob/v6.18/fs/nfs/Kconfig),
[Linux LOCALIO documentation](https://docs.kernel.org/filesystems/nfs/localio.html).
These describe upstream interfaces; they do not establish Tower's installed
module build or authorize loading it.

## Mac client alternative approved

The user approved a real Mac client against a new disposable share, with no
Tower module loads or kernel-setting changes. The Tower client-module/mount
route remains deferred. A network Mac client can exercise its own buffered
writes and recovery without the same-host Linux LOCALIO path; it does not
verify all Linux client implementations. The server still shares Tower's kernel,
so namespace isolation must not be described as a separate failure domain.

The next fixture must match an explicitly observed client protocol, keep its
own network endpoint/export/recovery state, and avoid host export reloads,
production service controls or changes to global kernel parameters. Existing
file descriptors, buffered writes, fsync outcomes and independently observed
server bytes must be checked across pause/controller death and explicit recovery.
A timeout is uncertainty, not durable denial; client exit does not prove pending
kernel writes are gone. Teardown must account for the new client mount before
restoration/cleanup. Until these checks are accepted, production exclusion stays
false. Protocol coverage beyond the tested client remains an explicit gap.

`scripts/sqlite_nfs_mac_client_probe.sh` reads current NFS mount options using
`nfsstat -m`. It omits export/server paths and original mount defaults, reports
missing options as unknown, and never mounts or changes settings. The user's
current attempt to mount Tower returned `RPC prog. not avail` (mount exit 74),
so no successful client mount or protocol has yet been established. Diagnose
RPC registration/reachability before creating the disposable network fixture;
do not infer a kernel-module problem or restart production NFS from this error.

Primary references:
[Apple nfsstat manual](https://github.com/apple-oss-distributions/NFS/blob/main/nfsstat/nfsstat.1),
[Apple mount_nfs manual](https://github.com/apple-oss-distributions/NFS/blob/main/mount_nfs/mount_nfs.8).

### Mac network connectivity accepted; disposable recovery test prepared

The user's explicit NFSv3/TCP/2049 read-only mount now works. The Mac reports
hard/nointr/nolocks; no Tower client module was needed. Both explicit-address
NFS NULL probes answered on Tower. Missing RPC discovery registration remains
separate from endpoint availability; no service repair was performed.

The [Mac NFSv3 fixture](sqlite-mac-nfs-lab.md) now prepares a private export and
uses existing SSH for the real client. It preserves hard-mount semantics,
observes pending writes separately from fsync, verifies server bytes during
controller death, and explicitly tests delayed writeback on recovery. Actual
Mac/Tower acceptance is pending. Linux client module loads/mounts remain
unexecuted, and NFSv4/LOCALIO acceptance remains outside this fixture.
