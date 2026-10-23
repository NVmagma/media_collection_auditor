# Real Mac NFSv3 recovery fixture, without Tower module changes

This lab is separate from production media and remains pending Tower/Mac
acceptance. JSON is authoritative. Writer exclusion, restart inhibition and
SQLite production activation remain false/disabled.

## Accepted connectivity, not pause/recovery acceptance

The user's Mac (reported macOS 27.2) mounted the existing media export read-only
with explicit `vers=3,tcp,port=2049,resvport`. Current parameters report hard,
nointr and nolocks. Explicit-address RPC NULL probes on Tower answered for
NFSv3/v4; the RPC registration listing lacked program 100003. The older `-n`
probe failed even though the explicit universal-address probe succeeded. Do not
infer an unavailable kernel listener or change/restart production NFS from that
older result. The read-only media mount is not used for fixture writes.

## Run

In the Tower checkout on feature/sqlite:

```sh
bash scripts/sqlite_nfs_mac_lab.sh /mnt/media/sql_test
```

Keep that terminal open. Once `fixture_ready=true` appears, copy the generated
three-line Mac command into a **second terminal on the Mac**. It fetches only
the client driver from the Tower checkout through existing SSH, then runs it
with the new fixture's address/path/nonce. Python 3, SSH and sudo for the new
mount/unmount are needed on the Mac. No Python dependencies are installed.
The fixture has an approximately fourteen-minute server lifetime; start the
Mac command promptly. Retain both terminal outputs.

The client uses its own SSH control socket and two loopback forwards to the
new private container's 2049 and mountd 20048 ports. It publishes no Tower ports,
changes no SSH configuration and does not reuse or remount the existing media
share. NFSv3/TCP ports are explicit, so NFS service discovery is not required.
Only the bridge gateway may access the synthetic export; all clients are
squashed to an unprivileged UID. Only the new fixed payload file is writable.

## What is verified

1. The Mac checks the exact generated fixture marker before any write. It writes
   and fsyncs a fixed baseline through a held descriptor.
2. The private server pauses only its own NFSD instance, kills its pause worker,
   verifies zero private threads and unchanged baseline bytes, then acknowledges.
3. A child retaining that same Mac descriptor attempts a fixed buffered write,
   reports `write` and `fsync` separately, and stays pending if needed. After
   five seconds, fsync must not have completed. A returned write is uncertainty,
   not a durability or write-denial claim. Tower independently verifies bytes
   are unchanged while the private server remains stopped.
4. The client requests explicit fixture recovery. Only then does the private
   server resume. The client requires successful fsync; Tower independently
   verifies the delayed payload. This intentionally demonstrates why pending
   client writes cannot be treated as discarded by pausing the server.
5. The client closes/reaps its writer and cleanly unmounts the **new** mount
   before requesting fixture teardown. No automatic phase replay occurs.
   The launcher requires unchanged host exports, etab, service/configuration
   hashes, versions/listeners/RPC registration, module-name inventory and NFSD
   thread count before reporting overall success.

Expected final statuses are `real_mac_nfs3_recovery_fixture_complete` on the Mac
and `isolated_mac_nfs3_fixture_complete` on Tower. A paused report with
`write_outcome=uncertain` is expected, not a failure.

## Failure and scope

On a failure, no automatic server restoration is performed. The Mac retains its
new mount location, owned SSH tunnel PID and possible writer PID for review.
**Do not assume process exit or a timeout drains kernel writeback.** A hard NFS
operation can remain pending until recovery or explicit unmount. Do not reuse
that mount or run cleanup against any existing share. Preserve output and the
new fixture's server log before choosing recovery; no forced production unmount,
service restart or kernel repair is prescribed by the driver.

Tower must already expose nfsd, sunrpc and lockd in sysfs; missing prerequisites
block rather than load modules. Existing loaded NFS server support is exercised
inside new network, mount and PID namespaces, as in the previously accepted
NFSv3 RPC lab. This still shares Tower's kernel; it is not a separate kernel
failure domain. Private thread/version controls and private export/RPC state
are used, never production controls. The private server disables NFSv4 to avoid
unreviewed recovery/upcall paths. No module-loading command, global sysctl,
production export reload, production service control or Docker daemon restart
is performed.

This supplies real **Mac NFSv3** buffered-write/recovery evidence. It does not
verify NFSv4 clients, Linux LOCALIO, all client implementations, production
restart inhibition or a complete external-writer ownership model. In particular,
recovery releasing queued writes is a constraint for the maintenance protocol,
not permission to move media and restore arbitrary clients automatically.

Sources: [Apple NFS mount options](https://github.com/apple-oss-distributions/NFS/blob/main/mount_nfs/mount_nfs.8),
[Linux NFSD administrative interfaces](https://www.kernel.org/doc/html/latest/admin-guide/nfs/nfsd-admin-interfaces.html).

## Local validation

The maintained maintenance-only suite passes 232 checks on the development Mac.
The focused NFS set passes 50 checks. Tests use regular disposable files and
inert commands, not actual SSH mounts or kernel NFS controls. They establish
local protocol/isolation guards; the generated Tower/Mac run is still required
for real buffered-write/recovery acceptance.

## First Tower startup rejected; endpoint readiness corrected

`nfs-mac.zzCztY` exited before readiness: the private `rpcinfo -p` registration
dump returned AUTH_TOOWEAK (client credential too weak). The production thread
count remained eight. No real Mac buffered-write result was obtained.

Startup now uses bounded direct RPC NULL calls to private rpcbind TCP/111 and
mountd TCP/20048, with explicit universal addresses. This avoids requiring a
registration-table dump that is not used by the fixed-port client. Authentication
policy is not loosened: no rpcbind insecure option or host configuration change
is introduced. The precise installed-build reason for rejecting DUMP is not yet
established. Readiness tests cover successful endpoint calls despite a rejected
DUMP, unavailable endpoints that must block, and early-child-exit diagnostics.

Private rpcbind debug logging and failure-line/phase diagnostics are retained.
The launcher reports the child exit code and a bounded log excerpt without a
misleading kill error. Use a fresh lab, not the failed directory. Actual endpoint
startup and Mac recovery still require acceptance on Tower.
