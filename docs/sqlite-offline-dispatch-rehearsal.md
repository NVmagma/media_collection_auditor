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

### Retained request validation

The disposable verifier now requires the exact request schema and all six original
route records. Duplicate JSON keys (including nested keys), boolean schema or
identity numbers, malformed content digests, missing routes, extra fields and
changed production/exclusion flags fail before mount inspection. Rejection leaves
the retained request untouched; it never repairs, adopts or clears an interrupted
installation. This validates record structure, not authenticity or permission to
restore services. Expanded Linux mount acceptance and the production host package
remain pending.

The refreshed Tower scope observation confirmed single enabled SMB/NFS settings
with CRLF line endings and a single enabled Docker setting. Reviewed Samba/mover
script hashes matched; the move-helper hash remains observed without an independent
source match. These observations do not establish writer exclusion.

### Read-only interrupted-install review

For a retained **disposable fake-host tree**, run from the checkout:

```sh
python -B -m scripts.sqlite_offline_dispatch_review --root /absolute/disposable/fixture
```

This command never mounts, unmounts, executes a service, edits a record or takes
ownership of the interrupted attempt. It requires the marker and strict retained
request. Each fixed route is reported as its original identity and bytes,
guard bytes with mount ownership unverified, or a conflict. Root/scope/digest
mismatches remain explicit blockers. Repeated artifact reads reject detected drift
rather than returning mixed evidence. The report omits source content and hashes.

Every report remains `review_required` with `restoration_authorized=false`.
Matching original files is not proof that no mount was installed; matching guard
bytes is not proof that a mount belongs to this request. Mount ownership and an
explicit owned-change recovery implementation remain required before restoration.
This report is not a production host recovery tool and supplies no writer permit.

### Refuse pre-existing dispatch changes

Installation now rejects any exact target mount before capturing originals and
again before writing the pending request. Original content already equal to the
fixed guard is rejected as unowned. Each target is checked once more immediately
before its bind action; a conflict at that stage retains the durable request and
any completed guards. Missing, empty, oversized or malformed mount inventories
fail closed. The same bounded parser supplies complete guard verification.

These are admission checks, not continuous mount exclusion: an external actor
can still race an observation. They neither make another installer's mount owned
nor enable automatic recovery. Actual Linux acceptance of this expanded installer
remains pending; portable tests use synthetic mount inventories and never mount
anything on the development Mac.
