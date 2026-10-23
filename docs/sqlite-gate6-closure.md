# Gate 6 closure work

Gate 6 remains open. Accepted disposable tests are evidence for individual
requirements; they are not a production ownership permit. JSON authority,
disabled SQLite activation and deletion safeguards remain unchanged.

## Accepted components

- Held directory/mount binding, no-overwrite publication, source retention and
  atomic disposable lifecycle checkpoints have Unraid acceptance.
- Real Jellyfin 12.2.0 reads protections with read-only media, including after
  fixture restart. A RO parent does not cover a RW nested mount.
- Real Mac NFSv3 delayed-write/fsync recovery passed without Tower module loads.
  Paused bytes remained unchanged; queued writes arrived after explicit recovery.
- Disposable Docker failure restart, persistent restart=no and controller-death
  behavior passed. Explicit starts/recreation and daemon/host boot remain outside
  that result.

## Three closure requirements

| Requirement | Work remaining before acceptance |
| --- | --- |
| Enforced ownership and continuity | A real maintenance adapter must cover every relevant container/host/share writer, their storage aliases and pending writes, and administrative restart/recreation/boot paths. It must remain fenced across controller death; no receipt or operator boolean substitutes for enforcement. Separate Mac v3 and Linux guest v4.1/v4.2 evidence exists; Tower LOCALIO and production startup fencing remain unverified. |
| Safe source-entry action under ownership | Bind verified source/destination objects to the accepted ownership boundary. Existing renameat2 no-replace protects the destination but is not inode-conditional source rename. Pre/post checks alone do not eliminate source substitution. Retain originals and pending intents on uncertainty. |
| Integrated crash/recovery acceptance | Rehearse the accepted adapter and verifier together, including boundary loss, queued client writes, source substitution and unknown commit outcomes. Recovery must retain evidence and never automatically reopen writers or clear intents from a matching path/hash alone. |

These are implementation and acceptance requirements, not three more smoke-test
runs. Repeating the accepted NFSv3/Jellyfin tests cannot close them. A future host
adapter will need a concrete reviewed change package before any production
service/startup modification; none is installed by the present work.

## Hard-link ownership gap

A file can have another hard-link name in a download directory or outside a
reviewed media tree. A media-mount write policy cannot establish exclusion of
that other name. Live verified copy-completion checks now reject regular files
whose link count is not exactly one, both before/after opening and at the current
entry binding. The check applies recursively to source and staged/published
copies wherever hash evidence is refreshed/verified. It never removes an alias
or rewrites production data.

Copy-only source-retaining diagnostics still copy those bytes independently and
report no promotion authority. The existing JSON production path is unaffected.
The completion runner blocks pre-existing aliases before durable intent; aliases
introduced later retain pending intent, clocks and original bytes without
publication, quarantine or Arr queue changes at the tested boundaries.

This is a conservative capability/ownership condition, not a filesystem-name
restriction. `nlink=1` is not an ownership permit: bind aliases, existing writable
handles, alternate network routes and races after checks remain separate. There
is no ignore-hardlinks switch. A future backend accepting shared inodes needs an
independently reviewed alias/exclusion model, not a weaker digest comparison.

## Focused Unraid check

```sh
bash scripts/sqlite_copy_ownership_checks.sh /mnt/user/sql_test /mnt/media/sql_test
```

Uses only the cached pinned Python image and new lab subdirectories. Sources
are read-only; only app/tests/requirements are mounted, excluding checkout .env,
production state/media and Docker sockets. Dependency installation uses network
access inside the temporary container; tests use fake collectors. There is no
image build, NFS control, module operation or existing-container update. Lab
artifacts are retained. The user accepted 43 checks on each path with the
corrected launcher through `b484fd9`.

Local verification: 45 focused checks pass, including real hard links and the
inert launcher's source/mount restrictions. The broader maintained run passed
892 checks and 19 subtests but its existing loopback HTTP smoke test hit sandbox
EPERM on socket bind. That five-check HTTP module passed separately outside the
bind restriction; no application assertion or safety guard was changed for it.

### Focused launcher startup correction

The first Tower run stopped before pytest: executing the generated
`/tmp/testenv/bin/pip` script returned permission denied. This supplied no
hard-link test result. Installation now uses the venv interpreter's `-m pip`
entry point, matching the existing `python -m pytest` pattern. The interpreter
symlink resolves to the base runtime outside the temporary mount. `/tmp` is
explicitly noexec/nosuid/nodev; no executable-mount permission is added.

A regression creates a real venv, removes the pip launcher's executable bits,
and verifies module invocation still works. Inert Docker tests also require
noexec and interpreter/module invocation. Actual Tower acceptance requires a
fresh launcher run; failed lab artifacts remain retained.


## Durable uncertain-client hold

The marked disposable maintenance journal now has a deny-only writeback hold.
It records the fixed uncertain-client outcome transactionally under the existing
controller lock and scope checks. It does not advance the lifecycle event revision
or claim that fencing succeeded. Every subsequent transition checks the hold,
so even a caller with the previous matching revision cannot advance/release.
The synthetic release receipt is not created, and old/new cooperative writer
descriptors cannot write after the hold. An unknown/empty hold schema also blocks.

Real child-process exit after commit preserves the hold. Detached read-only
review reports `client_writeback_outcome_uncertain`, without changing source
bytes or granting resume/clearance. There is no clear/delete/force/replay API.
A failed record must abort any proposed external step; a future adapter must
persist the appropriate request/uncertainty state before risking an external
operation, not rely on successfully logging a failure afterwards.

This is fixture journal enforcement, not an external NFS/Docker fence. It is not
wired to production services or represented as production writer exclusion.
Existing journals without a hold keep their synthetic behavior and grant no new
production authority. A released fixture cannot retrospectively record an active
hold; production release still requires an independently accepted client-state
and ownership model. The user accepted 66 checks on each Unraid path through `ed0c919`, including
the committed hold surviving process death and blocking release/writes.

Run the focused new regression set using only disposable directories:

```sh
bash scripts/sqlite_maintenance_writeback_checks.sh /mnt/user/sql_test /mnt/media/sql_test
```

The fixed copy-ownership and maintenance-writeback wrappers share the isolated
boundary-check launcher. It mounts app/tests/scripts/requirements read-only,
uses a noexec temporary mount and `python -m pip`, and accepts no arbitrary suite
or command. The scripts mount allows the detached review CLI tests; checkout
.env, state, production media and Docker sockets are not mounted. No NFS controls,
service changes, kernel operations or image builds are involved.

Local validation for the hold increment: 72 focused checks pass and the maintained
maintenance-only suite passes 250 checks. The user subsequently accepted 66 focused checks on each Unraid path. These
results do not claim a real external-writer fence.


## One-shot maintenance/media integration prepared

The [maintenance-bound copy wrapper](sqlite-maintenance-bound-copy.md) now joins
the existing boot/session-bound journal and live copy verifier for a single
marked disposable operation. It commits the operation/root/database binding
before work, holds both cooperative locks, observes fresh journal state at
verification boundaries, refuses existing holds or drift, and never replays a
retained attempt. Only live core completion can record verified outcomes;
maintenance is never automatically released. The user accepted 38 checks with
3 capability skips on shfs and all 41 checks on the native path through `096ca65`,
including the native publication/quarantine fault cases. No external-fence claim
is made from this wrapper.


## Startup control discovery before host adapter implementation

The read-only `scripts/sqlite_startup_control_probe.py` reports exact yes/no
Docker/NFS enable preferences, fingerprints startup scripts (including go, without
displaying or executing its contents), and validated container names/delays from
`/var/lib/docker/unraid-autostart`. Unknown/malformed input remains unverified.
It does not invoke Docker, service controls, shell configuration or kernel controls.

The pinned [Unraid rc.docker source](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/etc/rc.d/rc.docker)
uses this autostart list to call docker start separately from container restart
policies. The actual host source fingerprints still need review. Disabling a
restart policy alone is therefore insufficient. This discovery cannot establish
boot ordering, exclude administrative recreation, or grant ownership. A concrete
host change package and integrated acceptance remain required before Gate 6 closes.


### Tower startup observations accepted (2026-10-23)

The first probe was incorrectly launched inside the auditor container. Its
unavailable host files are not host evidence. The probe now explicitly reports
`wrong_execution_context` when a Docker container marker is present. Absence of
that marker is not proof of a host namespace or permission to enforce anything.

The subsequent host-terminal snapshot reports Docker enabled, 24 Unraid
autostart entries, and matching Docker service aliases with SHA-256
`0528b5a5ea967a0f64675f61381eadd922a9538b16dcd36b7b1a635d78b955c2`.
The pinned upstream rc.docker bytes were downloaded and independently hashed to
the same value. Both start and restart dispatch asynchronous container startup
from `/var/lib/docker/unraid-autostart`, separately from Docker restart policies.
Auditor, Jellyfin, Radarr, Sonarr, NZBGet and Homepage are among these entries.
Names in this list do not prove that those containers exist, run, or write media.
Homarr's absence does not exclude direct starts or recreation.

The host rc.local fingerprint matches the earlier reviewed source. The custom
go fingerprint is `6e640b0b9f7d2777569ae2c2fc8f5d8e93f42c937a7b34e58a62c029e8952146`;
its contents were subsequently supplied and reviewed below; management-service
startup ordering remains unverified. The exact quoted yes/no filter
produced no NFS setting: missing, alternative formatting and other values were
not distinguished. This must not be interpreted as disabled NFS.

Before a production adapter can be accepted, its change package must identify:

1. Durable pending-maintenance state outside disposable controller processes,
   with boot recovery refusing automatic media work and service restoration.
2. Every legitimate service/container start and recreation route, including
   background Unraid autostart and dashboard Docker access. Editing only the
   autostart list or restart policies cannot enforce this boundary.
3. A reviewed boot ordering mechanism that applies before writers start; a
   late go-script hook alone cannot establish that ordering.
4. Pending NFS client writeback handling before collecting an authoritative
   media baseline, and explicit recovery before reopening access.
5. Integrated failure acceptance and a manual rollback/recovery procedure that
   retains originals and uncertainty records. Unknown state never restores
   writers automatically. Arbitrary privileged bypass cannot be represented
   as excluded merely by a shell wrapper or cooperative lock.

No host installation, service control, startup preference edit or kernel change
is performed by this discovery increment. Gate 6 remains open.


### Custom go script review

The user supplied the full go script: it starts `/usr/local/sbin/emhttp`, then
runs `chmod 666` on `/dev/sr0`, `/dev/sg2` and `/var/run/docker.sock`. No direct
media copy or container-start command appears in this script, but emhttp launches
the management service; this is not evidence that no writers start indirectly.
Because emhttp starts before these permission changes, this script is not a
pre-management maintenance guard. An unsuccessful chmod is possible, so the
script describes intent, not a fresh assertion of live socket permissions.

The world-writable Docker socket intent expands the administrative control route
beyond dashboards. A process able to reach the socket may request container
starts/recreation without a dashboard. A maintenance design cannot limit its
control inventory to Homarr/Homepage or treat read-only socket binds as denial.
Changing socket permissions alone also cannot revoke already-open connections,
exclude root, or guarantee permissions after daemon recreation. Optical-device
permissions remain relevant to the separately reviewed privileged MakeMKV route;
they are not by themselves evidence of a Movie/TV write.

The startup probe now reports socket type/mode/owner metadata only, without
connecting or dispatching any Docker API operation. Container metadata describes
that container's view only; the wrong-context result remains explicit. This
observation never authorizes enforcement. No permission changes, startup edits,
service controls or production work are introduced. Host remediation must be a
separately reviewed change package with explicit operator approval.


### Live socket observation and retained-attempt review

Tower subsequently reported the live Docker socket as mode 660, owner root,
group docker. It is not currently world-writable. The go-script chmod intent
must not be substituted for this observed live state; why the states differ
was not established. Docker-group membership, socket-mounted containers, open
connections and recreation remain control routes to review. No chmod is needed
merely to accept this observation.

The detached maintenance reviewer now validates the copy binding's object type,
row cardinality, canonical absolute path syntax, nonnegative integer identities
and safe operation ID. It never follows the stored path or opens the associated
media database. Malformed/view/empty/duplicate bindings remain explicit blockers.
Paths, inode/device identifiers and operation IDs are not returned in the report.

A structurally valid binding reports only identifiers, not ownership. The
checkpoint distinguishes work_pending from outcomes_recorded, with media outcome
not independently verified and retry/original-retention authority always false.
In particular, the media checkpoint may commit while the maintenance phase stays
work_pending: the injected completion-checkpoint fault test requires the report
to remain uncertain and refuse automatic retry. No history record proves current
media bytes or permits a resume. Source database bytes and sidecars remain
untouched by detached review.

This improves recovery evidence for Gate 6's integrated acceptance requirement;
it does not implement the missing host fence or close the gate. The existing
maintenance-bound-copy focused launcher includes these regressions on both paths.


Tower accepted the retained-binding review through `5f26bb6`: 51 passed with
three capability skips on shfs, and all 54 passed on native storage.

### Explicit detached media comparison

An optional `--media-root` on the maintenance review CLI compares the retained
binding with an explicitly supplied canonical, marked disposable media lab. It
never follows the path stored in the maintenance database. Both main databases
are read as bounded detached images; SQLite never opens the source files.
Unresolved sidecars are preserved and block review. Root/database/marker
replacement during the observation discards the report. No runner lock is
created, no migration/recovery/checkpoint runs and no network collection occurs.

The result reports identifier comparison and whether a pending operation ID
matches, differs, or is absent. Absence is explicitly not completion proof: the
media transaction can commit before the maintenance checkpoint does. Operation
IDs, media paths and title details stay redacted. This is neither a coherent
cross-database transaction nor verification of media bytes/protections/retained
originals; no combination grants retry, clearance, writer release or production
authority. Existing writeback holds and scope blockers remain authoritative.

This advances integrated recovery diagnostics, not external writer enforcement.
Actual ownership/continuity and production integration remain Gate 6 blockers.


Tower accepted explicit detached media comparison through `d024988`: 62 passed
with three capability skips on shfs, and all 65 passed on native storage.

### Abrupt process-death acceptance prepared

The maintenance-bound integration suite now starts a separate Python process
that creates its own actual boot/network/controller-bound journal and media lab.
It uses `os._exit(23)` during collection, and at each existing injected
retirement-intent, source-quarantine and media-completion-checkpoint boundary.
For completion cases, only construction of the test-injected crash exception
is replaced in the child, so exit precedes Python stack unwinding; no filesystem
syscall, identity verifier, lock or lifecycle guard is replaced. Production
code is unchanged. This tests process death, not power loss/disk-cache durability.

The parent requires the requested exit code, retained original bytes, no release
receipt, uncertain detached evidence and rejected adoption by a different
controller process/session. A committed media checkpoint with no pending record
still reports no completion proof. Read-only review and rejected replay must not
change retained file bytes. Unsupported atomic publication verifies original
and intent retention before explicitly skipping unreachable crash boundaries.

The collection-death case runs locally; actual Linux completion cases need
Tower acceptance via the same focused launcher. Mac boot/network readers are
explicitly simulated for the protocol-only collection case. No Tower module,
NFS/Docker service, startup or production media changes are involved. These
checks advance the integrated disposable crash evidence only; actual host
writer exclusion, restart continuity and production integration remain open.


Tower accepted abrupt controller-death checks through `74d93ab`: 63 passed with
six capability skips on shfs and all 69 passed on native storage. This accepts
process exit at those disposable boundaries, not host power loss or enforcement
of external writer exclusion.

The user requires Unraid web management to stay available during maintenance.
The [control proposal](sqlite-maintenance-control-proposal.md) records that
constraint and evaluates a Docker daemon authorization boundary as a candidate,
with separate restart/NFS/boot limitations. It is not installed, tested against
a real daemon, or approved for production changes. Further repetitions of the
accepted copy suite alone will not resolve that architecture requirement.


The user supplied Tower's Engine 29.8.2 baseline: no authorization plugins and
live restore disabled. An offline deny-by-default Docker HTTP policy candidate
now has local rule tests; no listener, installer or daemon configuration is
introduced. This is implementation preparation only, with native gRPC, restart,
existing streams, host boot and NFS explicitly outside its enforcement claim.
See the control proposal for the required separate-daemon rehearsal.


The [local separate-daemon authorization rehearsal](sqlite-docker-authorization-rehearsal.md)
now supplies real Engine 29.8.2 HTTP allow/deny and plugin-death failure evidence.
It used a separate empty daemon, not Tower or a reconfigured existing daemon.
Status observations worked, mutations/streams denied, and plugin loss denied a
create request without creating nested containers. This advances the candidate
Docker API control only. Native gRPC, existing writers/streams, restart/boot
continuity, Unraid UI and NFS remain unverified; Gate 6 remains open.


The local separate-daemon restart rehearsal through `14a00af` passed: the HTTP
policy survived restart of that private daemon container, plugin death caused an
explicit create-request failure, and a further restart without the plugin failed
plugin validation. The private container inventory stayed empty. 69 local rule/
transport/startup/launcher regressions passed; all new fixture resources were
removed. See the separate-daemon rehearsal for failed-timeout investigation and
exact scope. This is not host boot, automatic workload restart, durable hold or
complete restart inhibition; those production blockers remain unchanged.


The candidate private Docker authorization endpoint now loads a fixed durable
deny-only hold. Real separate-daemon acceptance through `eb2ae98` confirms that
a new plugin process can reload unchanged hold bytes while mutations remain
denied; corrupting the hold denies observations too, and blocks the next daemon
startup via plugin validation failure. 82 local regressions passed, including
abrupt process exit and rejected concurrent listener adoption. This advances
deny-state recovery only: it does not authorize a maintenance session, release
writers, implement host boot controls or close Gate 6. All fixtures were removed.


Through `aad9329`, the private Docker candidate has persisted selected-ID scope
for stop and strict restart-disable-only updates. Real empty-daemon tests confirm
those two requests reach lookup for the absent selected fixture ID, while
out-of-scope or restart-enabling requests deny; scope survives plugin reload.
115 local regressions passed. An absent-ID 404 is not successful quiescence or
existing-writer acceptance. Actual writer stop/restart verification, complete
external routes, host boot and NFS remain open; production is unchanged.


The [independent guest writer rehearsal](sqlite-docker-writer-guest-rehearsal.md)
through `7140819` now supplies actual selected-writer evidence: a real always-
restart container wrote synthetic bytes, was restart-disabled/stopped through
the candidate and remained stopped with unchanged bytes after its private daemon
restarted. Start remained denied and selected-ID inspection confirmed state.
120 local regressions also passed. The separate-kernel guest was powered off.
This advances existing-writer component acceptance beyond absent-ID routing;
it does not establish all Tower writers, boot/NFS/administrative routes or the
integrated production media boundary. Gate 6 remains open.


The [independent NFSv4 guest rehearsal](sqlite-nfs4-guest-rehearsal.md) now
covers real kernel clients for both v4.1 and v4.2. After the pause controller
was killed, writes returned but fsync stayed pending and server bytes stayed
unchanged; explicit recovery delivered the pending bytes and allowed normal
unmount. Recovery helpers remained alive in accepted runs. Seven local guard
regressions passed. This closes the missing minor-version component experiment,
not production NFS ownership/restart inhibition or Gate 6. Tower's kernel,
LOCALIO, administrative routes and integrated maintenance boundary remain open.


The real guest Docker writer checkpoint now requires explicit stopped state:
matching full identity, Running/Paused/Restarting/Dead false, exited status,
integer PID zero, and restart=no with integer retry count zero. Missing or
ambiguous observations block. Real Engine 29.8.2 acceptance passed before and
after private daemon restart, with denied starts and unchanged fixture bytes;
113 focused local checks passed. This strengthens a required observation but
is not a fence or ownership receipt. Boot ordering, all control routes and
integration with the actual media boundary remain necessary for Gate 6 closure.


The [independent boot rehearsal](sqlite-docker-boot-guest-rehearsal.md) now
accepts actual guest reboot with persisted deny policy before private Engine
startup: selected writer stays stopped, starts deny and bytes remain unchanged.
Policy SIGKILL stops the bound engine. A second reboot with corrupt hold blocks
both services with unchanged media bytes. 85 focused local checks passed; fixture
units were disabled and the independent VM powered off. This is real prototype
boot/failure evidence, not Unraid startup/management acceptance or complete writer
exclusion. No production installer, release path or ownership permit is added.


Tower's listener snapshot identifies Docker Unix API and managed containerd
sockets; no named TCP listener was observed. Shared emhttp socket attribution
is not Docker API ownership and must not be used to fence management. The
independent guest negative-boundary experiment now confirms a native containerd
metadata update succeeds for a socket-authorized caller while Docker denies its
HTTP comparison mutation. `native_runtime_route_fenced=false` remains explicit.
The selected synthetic writer still passed stop/restart acceptance. Direct
runtime access/trusted administrative scope and prior streams therefore remain
real closure requirements, not a missing HTTP route rule. Tower is unchanged.


Tower's subsequent permission/ACL snapshot shows root-only 0700 parent runtime
directories and root-owned 0660 containerd sockets, without additional ACL entries
in supplied output. This narrows the native route to callers with actual access;
it does not show unprivileged dashboard access. Container-mounted sockets/parents,
elevated access and inherited handles remain review requirements. The advisory
mount reviewer now catches parent runtime directories, `.sock.ttrpc` and custom
declared control aliases, including read-only/stopped cases. It remains advisory;
no production permissions, services, guards or ownership claims change.


The updated host mount report observes 22 containers and flags 11. It identifies
the current auditor as a writable media client, dashboard Docker API binds, and
stopped privileged MakeMKV; these must remain separate from unresolved cache-volume
scope. Broad share overlap is not automatically a stop list for narrow Movie/TV
work. The control proposal records the role-specific interpretation.

The independent guest now accepts real selected-Docker-writer observations through
the maintenance-bound copy verifier. Healthy synthetic media completion retains
original bytes; policy death during collection blocks completion and retains the
attempt, source/state and work_pending phase without release. The optional observer
is deny-only, accepts no boolean authority and changes no production permission.
This advances integrated component acceptance; full external ownership, Unraid/NFS
controls and remaining action-boundary failure acceptance still block Gate 6.


Combined selected-writer/copy acceptance now includes real policy death at the
first live check after publication, quarantine and committed media checkpoint,
in addition to collection. Original bytes and work_pending maintenance remain;
committed media with no pending intent still grants no completion/release proof.
Same-controller retries and different-controller adoption were rejected for all
four cases without changing retained bytes. 69 local checks passed with six
platform skips; real guest action syscalls supplied the Linux component evidence.
Full host/share ownership and continuous production enforcement remain open.


The independent real NFSv4 client fixture now also joins observed pending writes
to a durable disposable maintenance uncertainty hold. Copy work is denied before
collection/attempt binding, both while fsync is pending and after explicit server
recovery/fsync/unmount. Recovery does not clear the hold or grant release. This
combines client uncertainty with the SQLite deny path, while leaving production
clearance and complete Docker/NFS/host ownership integration unimplemented.


The [unified controller contract](sqlite-unified-maintenance-controller.md) now
specifies separate host-controller placement, three mandatory control domains,
durable request-before-action ordering and production installation prerequisites.
The disposable verifier also rechecks local lock/journal scope after external
observation returns. Replaced media/controller locks block before attempt binding
or collection. 65 focused local checks passed with six existing platform skips.
This is an ordering fix and integration contract, not a production adapter or
accepted Unraid/NFS startup fence. No deployment authority is added.


A unified disposable admission wrapper now requires Docker, NFS and host/storage
checks together, including reverse rechecks and a latched failed checker. One
failed domain blocks before collection or attempt creation; adapter booleans and
receipts are not authority. Existing durable journal/hold/session checks stay
intact. This combines the control interfaces, not production enforcement: real
host adapters, complete scope, continuity and clearance remain unimplemented.


The live Docker observer has been extracted from the guest script into a reusable
marked-fixture backend. Real Engine acceptance includes copy completion, absent
selected writer denial, policy-loss denial and no automatic failed-observer reset
after policy reload. Directory/marker/socket and daemon/policy identities stay
bound; read timeouts and oversized/ambiguous responses deny. 98 local checks passed
with six platform skips. This supplies a real Docker observation adapter for the
unified interface, not complete production enforcement or inventory ownership.
NFS restart/boot and host/storage bindings remain necessary before Gate 6 closes.


Pinned startup sources were rechecked before choosing the production NFS design.
A plugin-only or go-only fence does not cover Safe Mode. The
[NFS host change draft](sqlite-nfs-host-fence-change-draft.md) identifies a
conditional persistent-disable/runtime-guard approach, backup/recovery requirements
and the missing implementation/acceptance. Administrative trust scope is a pending
design decision; no host-root bypass exclusion is silently assumed. No installer,
configuration change, service action or production readiness is introduced.



The administrator trust decision is accepted for the initial model; it is design
scope, not Tower change approval. A new disposable configuration planner prepares
exact original/disabled artifacts and refuses restoration candidates after any
intervening edit. Binding/content drift, unsafe file types and plan overwrites
block, with original source bytes retained. 87 focused checks passed with six
platform skips and the synthetic CLI passed. This is backup/review preparation,
not settings application, a live NFS fence or production ownership acceptance.


The live NFS observer now binds actual Linux boot/network/mount scope, stopped
kernel threads, empty kernel exports, disabled fixture preferences and both exact
read-only guard mounts/content. Real separate-VM acceptance denied 12 dispatches,
blocked guard mount-policy loss and refused automatic observer recovery. This
extracts another control-domain observer, not a Tower fence installer. The global
Unraid enable form is distinct from nfsSettings protocol/thread apply; no unsafe
HTTP/configuration shortcut is added. Production settings/boot and host/storage
ownership integration remain open.

Storage-domain increment: a marked disposable descriptor observer now binds the
root and stage paths to their Linux mount IDs and mount namespace without
requiring one filesystem. Replacement, namespace/mount drift, marker replacement
and closed/failed reuse reject. A combined-controller test verifies real stage
replacement blocks before collection or durable attempt binding. Local Mac tests
simulate only unavailable proc readers; real filesystem replacement is exercised.
Linux mount-overlay acceptance and complete host-writer enforcement remain open.
Production activation and writer-exclusion authorization remain disabled.

Actual independent Linux VM storage acceptance completed: mixed-mount baseline
accepted; same-device/same-inode overlay rejected by mount ID and the combined
required-domain callback; baseline detachment rejected; failed observer remained
blocked after restoration; original fixture bytes unchanged. Also closed a
capture-time root replacement gap by requiring the marker's held root descriptor
to match the captured root directory/mount. This satisfies the narrow Linux
mount-drift acceptance item above, not host writer exclusion or production move
admission. Full integrated host enforcement and boot/recovery closure remain open.

Combined live-domain milestone: the separate Linux VM ran the real disposable
copy with selected private Docker observations, stopped/export-empty NFS and
private read-only dispatch guards, and held storage/mount observations together.
The healthy copy completed with originals retained. Storage mount-ID loss at
collection, publication, quarantine and completion blocked verified outcomes,
retained attempts/originals and rejected retry without byte changes. In the last
case SQLite had committed, but that did not grant release or verified outcome.
The same four loss cases also passed with storage alone. Fixture guards and
synthetic collection/journal setup remain explicit limitations; no production
ownership permit, Unraid service installer, boot clearance or activation was
introduced. Remaining closure work is actual host enforcement plus integrated
boot/controller-recovery acceptance, followed by production lifecycle wiring
under a separately approved activation plan.

Retained-attempt recovery milestone: in the independent Linux VM, a replacement
controller sampled freshly healthy Docker/NFS/storage domains and then tried all
four retained loss cases. Each rejected specifically for controller-session
change, including the already-committed media checkpoint. After an actual VM
reboot, the same four cases rejected specifically for Linux boot change. Every
retained media/control byte remained unchanged, collection was unreachable and
no release receipt appeared. New private guard fixtures were explicitly prepared
for the checks; this is scope-rejection evidence, not automatic boot fencing or
restoration acceptance. Actual host enforcement/startup continuity remains open.

Initial host model narrowed with explicit user agreement: every Docker service
may pause, including unrelated services/DNS, while Unraid management and SSH
remain available. This permits an offline-Docker design instead of requiring a
live authorization service for that window; it does not authorize changing
Tower. Persistent opt-out plus runtime/startup verification are still required.

Tower has no host Python. A new cached-image export/chroot runtime rehearsal
avoids requiring a host Python installation. Restricted packaging and a fixed
host-launched program touch only a fresh lab, verify flock/SQLite, and preserve
artifacts. The separate VM passed with a synthetic local Python image, including
a read after its private Docker daemon stopped. Tower's cached-image execution
capability still needs a focused disposable check. No existing service is paused
by this rehearsal and no production controller/fence is implied.

Exact Docker-disabled configuration candidates now share the existing strict
preference parser and private artifact preparation with NFS. Only one canonical
DOCKER_ENABLED yes/no assignment is accepted, unrelated bytes stay unchanged,
and restoration candidates reject intervening edits. These are marked lab
artifacts only; no supported UI handler, host preference application or recovery
approval is implemented by producing them.
