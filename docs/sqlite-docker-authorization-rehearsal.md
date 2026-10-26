# Separate-daemon Docker HTTP authorization rehearsal

Local acceptance on 2026-10-23; not Tower deployment or Gate 6 closure.
JSON authority, disabled SQLite activation and deletion safeguards are unchanged.

## Actual environment and boundary

A local Docker Desktop 29.8.2 instance hosted a **separate nested Engine 29.8.2**.
Only the nested engine loaded the experimental authorization plugin. The existing
local engine was used to create/remove new fixture containers; its configuration
was never changed. Tower was not contacted. The official runtime was pulled:

`docker:29.8.2-dind@sha256:1e08cdb63405ca788aea94ef35b792d1e299607c667d33d7bcbcae1fd2611ced`

A cached local Python application image hosted the private plugin endpoint.
The fixture images were not built. Source app/scripts directories were mounted
read-only; checkout .env, media, production state and host Docker sockets were
not mounted. No ports were published. Containers used network none, bounded
memory/PIDs/CPU, no-new-privileges and no privileged mode. The plugin container
had all capabilities dropped and a read-only root filesystem. Its private named
volume held the new socket/spec files shared with the nested daemon.

The daemon bypassed the image's dind entrypoint and invoked dockerd directly:
no entrypoint modprobe, module operation or network setup was requested. It used
vfs, bridge none, iptables/ip6tables/ip-forward/ip-masq false, private data/exec/PID
paths and a private Unix Engine socket. All capabilities were dropped except
CHOWN and DAC_OVERRIDE. No nested workloads were launched. This capability set
is evidence for this empty-daemon HTTP test, not an approved container-execution
runtime or proof of safe arbitrary workloads.

Initial preflight failures were investigated: dropping every capability blocked
private socket ownership; CHOWN alone left another private socket permission
failure. An AppArmor-unconfined diagnostic attempt did not resolve it. The
successful run restored default security profiles and added only DAC_OVERRIDE.
No production security profile or host setting changed.

## Compatibility findings

`python -m scripts.sqlite_docker_authorization_fixture --root <new-private-root>`
creates a new private endpoint; an existing root is never adopted or replaced.
There is no production listener, installer, policy release or host-service API.
The protocol handler bounds body size, rejects duplicate JSON keys, has socket
timeouts and does not log payloads/credentials.

Actual Engine 29.8.2 plugin requests use `RequestUri` and may omit empty header
maps. Header maps can contain string values. The adapter explicitly normalizes
that observed shape before the policy evaluates it. Conflicting URI/header forms
remain denied. The earlier offline envelope caused status reads to deny too;
that was a failed compatibility result, not a success claim.

Legacy `.spec` discovery uses a plain Unix URI, not JSON. The successful private
setup exposed the spec under `/etc/docker/plugins/plugin.spec` and configured
`--authorization-plugin=plugin`. Empty activation POST bodies are supported.
These are fixture integration findings, not installation instructions for Tower.

## Observed daemon results

| Private Engine HTTP request | Observed status |
| --- | --- |
| GET /_ping | 200 |
| GET /version | 200 |
| GET /containers/json | 200 |
| POST /containers/create | 403 |
| POST /containers/no-such-fixture/start | 403 |
| POST /grpc | 403 |
| GET /events | 403 |

After killing only the private plugin container, a create request returned 500
with an authorization-plugin failure. Independent inspection of the nested
engine's private container-data directory found it empty. No automatic plugin
restoration was configured or observed. All three fixture containers and the
private volume created during the rehearsal were removed afterwards; existing
containers/daemon configuration were unchanged.

The create/start denials happened before a nested workload existed. This did not
exercise a running writer, start an existing container, prove denial of pending
streams, or test autonomous restart behavior. HTTP /grpc rejection is explicitly
not proof against native gRPC, which Docker documents outside HTTP AuthZ coverage.

## Regression scope and work still required

64 local policy/Unix-transport/startup-probe checks passed, including actual
request-shape normalization, status-read allowance, mutation denial, empty
activation and malformed/duplicate JSON rejection. These tests use private Unix
fixtures and do not access a Docker daemon. The daemon results above were a
separate manual local integration rehearsal, not those unit tests.

A production fence still needs reviewed versioned API/UI compatibility, native
gRPC/control-route coverage, previously established streams, durable hold and
boot continuity, real existing-writer quiescence/recreation/restart handling,
NFS pending writes, and integration with the media verifier/recovery model.
The Unraid web interface must stay available; this local test did not run Unraid
or verify its UI behavior. Do not install/reload this fixture on Tower to fill
those gaps. No maintenance permit, rollback action or recovery clearance follows
from any result here.

## Reproducible separate-daemon restart rehearsal

The subsequent local rehearsal through `14a00af` used
`scripts/sqlite_docker_authorization_restart_lab.py` and its bounded private
client. It requires an explicit Unix outer endpoint, verifies the outer engine
identifies itself as Docker Desktop (rejecting Tower/Unraid before resource
creation), and accepts cached immutable image IDs only. No pull/build occurs.
The outer daemon is only used to create/inspect/remove uniquely named private
fixtures, never reconfigured. It is not a production installer.

The launcher creates a fresh private volume, a read-only capability-free plugin
container and a separate CHOWN/DAC_OVERRIDE-only daemon. Both have no network,
no privileged mode and no host Docker/media/state mounts. The daemon has private
socket/data/exec/PID paths, vfs storage and no bridge/firewall/forwarding setup.
It restarts only that newly created daemon container; no host or daemon service
restart is requested. Cleanup removes only the resources created by this run.

| Phase | Accepted local result |
| --- | --- |
| Initial private daemon | Ping/version/container list 200; create/start 403 |
| Same private daemon container restarted, plugin still available | Same 200/403 policy results |
| Plugin container killed | Create returns explicit plugin-error 500; private container inventory empty |
| Private daemon restarted with plugin still unavailable | Nonzero exit with plugin-validation startup failure |

A first client used a 15-second timeout and timed out during the daemon's plugin
retry interval. That supplied no explicit-denial acceptance. A bounded 35-second
client window produced the required plugin-error response; a timeout still fails
the test and never becomes a denial success. The final run also required the
plugin-specific startup diagnostic, so an unrelated nonzero daemon exit cannot
satisfy this phase. No denied application request is automatically retried.

All new containers/volume were removed on completion. No plugin was restored,
no production services were controlled and no kernel/module changes were made.
69 local policy/transport/startup/launcher regressions passed. The orchestrator
unit tests use fake Docker commands only to check target restrictions, resource
isolation and cleanup; they are not the real-daemon evidence in the table.

This is an empty-daemon container restart, not Docker Desktop VM reboot, Tower
boot, power loss, persistent maintenance-state recovery or automatic restart of
an existing writer. The plugin is always in maintenance mode; no durable hold
loading/release or policy reconfiguration continuity is accepted. Native gRPC,
previous streams, actual writer quiescence, Unraid UI compatibility and NFS
remain open. `restart_inhibition_verified` and production authorization remain
false in every result.

## Durable deny-only hold reload

The next increment through `eb2ae98` adds fixed persisted `maintenance.hold`
evidence to the **disposable** authorization endpoint. The hold records schema 1,
fence_requested and automatic_restoration false. Initial creation uses exclusive
files, full writes and file/directory fsync. Partial initialization is retained;
there is no repair, expiry, release, success flag or force-clear API.

The listener holds a persistent flock inode. Marker/hold/lock objects must be
regular, single-link and bound to their opened directory/entries. Reads are
bounded, no-follow and nonblocking. Every protocol evaluation checks the live
binding before and after dispatch. Missing/unknown/corrupt/replaced state denies
even observation requests and activation. An absent verifier also denies.
This mechanism is not an external-writer lock or production ownership permit.

`--resume-fixture` explicitly reloads an existing **deny-only** fixture. It does
not initialize missing evidence. It requires the existing hold, marker and spec
and acquires the same persistent lock before removing a stale socket. A second
cooperating active listener blocks adoption without unlinking its live socket.
Reload neither rewrites the hold nor changes its phase. It is not resumption of
media work or adoption of a dead maintenance controller's execution authority.

Local real files/process tests cover exclusive creation, missing/malformed/
released-looking/symlink/hard-link/FIFO holds, binding replacement, committed
state surviving os._exit without cleanup, and a killed listener replaced by a
new process using the same evidence. Mac test paths were canonicalized to
/private/tmp rather than weakening the canonical-path requirement.

The separate Engine 29.8.2 rehearsal then passed:

| Phase | Observed result |
| --- | --- |
| Original daemon and after private daemon restart | Reads 200; writes 403 |
| Original plugin process killed | Explicit plugin-error 500; nested inventory empty |
| New plugin process explicitly reloads existing hold | Hold digest unchanged; reads 200; writes 403 |
| Fixture hold deliberately corrupted | Ping and create both 403 |
| Private daemon restarted while hold remains invalid | Nonzero exit with authorization-plugin validation failure |

82 local rule/transport/hold/startup/launcher regressions passed. All fixture
containers/volume were cleaned up. No Tower service, socket permissions,
configuration, NFS, media or kernel setting changed. No image build/pull was
needed for this increment.

This accepts process-level deny-state reload and corruption handling, not power
loss, host boot integration or atomic activation of a fence around preexisting
writers. A matching hold or digest cannot prove external exclusion, fresh media
protections or source retention. NFS pending writes, native gRPC/control routes,
existing streams/writers and Unraid management compatibility remain independent
requirements. All production and complete-restart-inhibition fields remain false.

## Selected-ID reduction-only quiesce routing

The increment through `aad9329` adds an optional bounded list of full 64-character
container IDs to the private fixture. Empty scope remains the default. Scope is
created exclusively as canonical `quiesce.json`, fsynced with the hold directory,
verified at each request and reloaded without an override option. Names, short
IDs, duplicates, malformed or oversized scope cannot initialize a hold. Old
fixtures without scope evidence fail closed; no migration/repair is performed.

For IDs in that scope only, the candidate admits exactly:

- POST to the unversioned container stop route, without body/query/upgrade.
- POST to the unversioned update route with exactly RestartPolicy Name no and
  integer MaximumRetryCount zero, and no other update fields.

The update decoder requires canonical valid base64 for the Engine envelope,
UTF-8 JSON, exact field names, no duplicate object keys, JSON content type and
consistent body length when supplied. Restart-enabling values, bool/float retry
counts, unrelated fields, framing ambiguity, upgrades and unknown routes deny.
No owner header/root identity can broaden those rules. Start/restart/unpause,
exec, kill, archive and recreation remain denied. This is fixture policy, not a
production controller or permission to stop any existing service.

The rationale is that HTTP authorization alone does not replace automatic
restart handling. Docker documents that a manually stopped always-policy
container can return after daemon restart:
[Docker restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/).
Disabling restart and verifying actual stopped state must occur before any
future authoritative media baseline. A configuration response or stop reply
alone cannot establish complete writer exclusion or drain all pending writes.

The local separate daemon was deliberately empty. With a single absent synthetic
ID selected, its stop and restart-disable update returned 404, demonstrating that
the request passed authorization and reached container lookup. Stop of a different
ID, start of the selected ID, and update to restart always returned 403. The same
404/403 pattern passed after a new plugin process reloaded the persisted scope.
HTTP 404 is **not** successful quiescence: existing_writer_verified remains false.
No existing workload was started, stopped, updated or otherwise targeted.

The prior read/deny, daemon restart, plugin-death, unchanged hold reload and corrupt
hold startup-failure checks also passed. 115 local policy/hold/transport/launcher
regressions passed. All private containers/volume were cleaned up. No image build
or pull, Tower changes, host kernel changes or production controls occurred.

Remaining acceptance includes an actual disposable writer stopped/restart-disabled
under the candidate, fresh independently bound state verification, restart
continuity with that writer, native gRPC/previous streams, host boot and NFS.
This increment supplies request-filtering evidence only and closes no gate.
