# Offline-service dispatch guard rehearsal

This page records the original two-service Linux acceptance. The current
expanded six-route fixture and its pending Linux acceptance are described in
the [SMB/mover source review](sqlite-smb-mover-source-review.md).

Tower's disposable controller runtime passed with Python 3.12.15, SQLite 3.46.1,
exclusive locking and a persisted synthetic checkpoint. That confirms the cached
runtime mechanism, not a host fence or production move permit. The initial
maintenance design allows all Docker services and NFS shares to pause, with
Unraid web management and SSH available.

`app/sqlite_disposable_offline_dispatch.py` implements a one-shot installation
primitive **only beneath a marked fake host tree**. It writes/fsyncs a pending
request before the first mount operation. The request binds the root and Linux
boot/network/mount scope, original dispatch identities/hashes and fixed guard
bytes. Controller lock, marker, request, guard source and alias bindings are
rechecked between external actions. Missing durability or changed bindings stop
installation and retain the request. No restart, release, settings-operation or
request-adoption API is provided.

The fixture imitates Unraid's `/etc/rc.d` symlink to `/usr/local/etc/rc.d`. Each
canonical fake `rc.docker`/`rc.nfsd` gets one read-only/nosuid/nodev guard mount;
both aliases must resolve to it. Originals are inert scripts, so a broken guard
cannot accidentally execute a real host service. The observer requires exact
mount inventory, bytes and scope; it returns no ownership credential.

The original acceptance ran `python -B -m scripts.sqlite_offline_dispatch_guest_lab --root NEW_PATH` only
in the dedicated independent Linux VM. It creates a private mount namespace,
started the fixture installer as a separate process and verified 22 fixed dispatch
denials, kills the installer with SIGKILL, verifies all 22 again and rejects a
replacement installation from the retained request. The request remains byte
identical. Namespace exit removes only fixture mounts; the outer harness then
verifies the underlying inert originals are unchanged. This cleanup is not a
production rollback or proof that a guard survives an actual host reboot.

`--partial` pauses the real installer just after the first bind mount, using a
fixture-only process barrier around the actual mount call. SIGKILL there leaves
ten Docker alias dispatches denied, but the complete binding rejects both before
and after death. The remaining NFS alias is deliberately unguarded; no complete
fence or work authorization is reported. Request adoption/reinstallation remains
blocked and originals remain intact after namespace cleanup.

Both modes passed in the independent VM. Neither uses live service paths,
preferences, Docker sockets, exports, media or module controls. No production
writer exclusion or restart-inhibition flag is enabled by these results.

## Required host scope review before installation design is finalized

`scripts/sqlite_offline_host_scope_probe.sh` reads selected SMB/NFS/Docker enable
preferences, Samba/mover source hashes, counts of scheduled entries/mover mentions
and selected process-name observations. It never sources configuration, executes
service/mover helpers, prints raw cron commands/credentials, changes preferences
or stops services. A fixture test includes executable-looking cron contents and
secret values and verifies neither executes nor appears in output.

Run this probe on the Unraid host, outside containers. Its output remains
`host_writer_scope_review_required`; absent processes and matching hashes are
observations only. The user identified NFS as their client protocol, but that
alone does not verify that another host share service is disabled. Likewise,
stopping Docker does not fence Unraid's own mover/scheduler. The actual host
observations determine whether additional fixed controls belong in the reviewed
installer package. No approval to change those services is inferred from the
Docker/NFS pause design.
