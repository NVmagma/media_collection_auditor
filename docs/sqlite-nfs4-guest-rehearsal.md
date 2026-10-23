# Independent Linux NFSv4 client recovery rehearsal

Accepted in a disposable QEMU guest on 2026-10-23 for NFSv4.1 and NFSv4.2.
This is component evidence, not Gate 6 closure or production writer exclusion.

The environment is the independent Ubuntu ARM guest described in
[the writer rehearsal](sqlite-docker-writer-guest-rehearsal.md), kernel
6.8.0-147-generic. NFS utilities were installed only in that guest, with package
service startup suppressed. Existing guest kernel modules were loaded there.
No Tower, Mac or Docker Desktop kernel modules/settings were changed. No Tower
exports, production media, Docker socket or service controls were accessed.

`scripts/sqlite_nfs4_guest_lab.py` requires the dedicated fixture hostname,
NoCloud instance ID, Linux root, no existing RPC actors, an empty export inventory
and zero existing NFSD threads. These are accidental-target guards; VM isolation
is the boundary. Never run this script on Tower. It is not an installer.

The server binds a private guest veth address. A real kernel client runs in a
separate network and mount namespace, with no default route. Only a new synthetic
payload is exported, to the exact private client address. The client requests an
explicit minor version over TCP and checks the mounted version. NFSv3 is disabled.
There is no forwarded NFS port or production client involved.

For each minor version, the client first writes and fsyncs baseline bytes. A
new pause controller stops guest NFSD and is then killed. The client writes
through its already-open descriptor; its write returns, but fsync remains
pending. Client network transmit bytes increase while independently observed
server payload bytes remain unchanged. Only explicit fixture recovery restarts
NFSD. The pending fsync then completes, server bytes match the pending payload,
and the client unmounts normally. Forced/lazy unmount is never acceptance.

Both accepted runs reported `private_guest_nfs4_recovery_complete`, with the
recovery and mount helpers alive through completion. Initial attempts under the
user's non-traversable home failed recovery storage access; that result was not
accepted as a healthy setup. Fresh root-owned labs under guest `/var/tmp` resolved
the failure without changing home permissions. A new helper-health check now
blocks acceptance when either helper exits. Earlier setup failures also exposed
a missing pipefs directory and unsupported NFSv2-disable option; both were fixed.

Seven local tests cover accidental targets, existing exports/actors/threads and
helper failure. Actual protocol evidence comes from the guest runs, not mocks.
Synthetic logs/checkpoints were archived to the host temporary lab, the exact
fixture exports/namespaces were removed, and the guest was powered off.

The evidence reinforces the durable writeback hold: stopping server threads or
killing a controller does not cancel a client's queued write. This does not test
Tower's kernel, Linux LOCALIO, real production clients, host reboot, NFS restart
inhibition, all administrative bypasses, concurrent workloads or the integrated
SQLite ownership boundary. There is no automatic restoration, clearance or
production permit. JSON remains authoritative; production activation and deletion
remain disabled.
