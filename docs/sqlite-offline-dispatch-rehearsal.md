# Offline-service dispatch guard rehearsal

This page records the original two-service Linux acceptance and the expanded
six-route Linux acceptance below. The scope review is in the
[SMB/mover source review](sqlite-smb-mover-source-review.md).

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
restore services. Expanded Linux mount acceptance is recorded below; the production host package
remains pending.

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
nor enable automatic recovery. The Linux acceptance below exercises the expanded installer. Portable unit tests
use synthetic mount inventories and never mount anything on the development Mac.


## Expanded real Linux acceptance (2026-10-23)

The expanded installer and recovery review passed in a newly created local Docker
Desktop Linux container, using cached immutable image ID
`sha256:01b4f1f7237d28a502d8cf43dd6d3bb47c61ffdd4189bf6a3d24e9a256307fcf`.
No image was downloaded or built. The fixture uses the image's Python 3.10 runtime;
it does not replace the separately accepted Tower Python 3.12 runtime test.

| Actual check | Result |
| --- | --- |
| Complete six-route installation | 49 dispatches denied before and after real installer SIGKILL |
| Partial installation, killed after first bind | 10 Docker dispatches denied before and after death; complete binding rejected |
| Retained recovery review | Six guard routes in complete case, one in partial; restoration denied in both |
| Replacement installer | Refused retained request in both cases |
| Durable pending record | Bytes unchanged after controller death and review |
| Underlying inert originals | Original hashes match after the private mount namespace exits |

The launcher `scripts/sqlite_offline_dispatch_container_lab.py --image FULL_IMAGE_ID`
streams only Python sources and a fixed fixture marker into new container tmpfs.
It requires a cached full image ID and never pulls, builds or installs dependencies.
There are no host binds, devices, service sockets, host namespaces or network.
The image filesystem is read-only. Only `SYS_ADMIN` is added after dropping all
capabilities; seccomp/AppArmor restrictions are lifted for the fixture's actual
private mount/unshare operations. This is a disposable test capability, not an
application deployment profile. A dedicated hostname, container marker, tmpfs root
and absence of shared mount propagation are checked before rehearsal dispatch.

The new container is removed on completion/failure; fixture tmpfs is discarded
only after the assertions above. No Tower service or setting was touched. This
container shares Docker Desktop's Linux kernel: it proves mount/installer-death
behavior, not an independent reboot, Unraid normal/Safe Mode startup inhibition,
existing writer quiescence, fresh protection collection or production ownership.
