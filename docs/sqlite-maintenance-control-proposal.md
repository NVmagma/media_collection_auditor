# Gate 6 maintenance controls: management stays available

Status: design proposal, not installable enforcement or permission to change Tower.
JSON remains authoritative; SQLite production execution and deletion stay disabled.

## Required availability

The user requires Unraid web management to remain available during the initial
maintenance window. The earlier design choices allowing all NFS shares and both
dashboards to pause still apply, but do not authorize stopping them. Do not solve
administrative restart coverage by stopping emhttp or blocking its startup.

Tower's live Docker socket is root:docker mode 660. Its custom go script contains
chmod 666 after starting emhttp, but the live observation is authoritative for
that instant. Neither fact establishes future permissions or request denial.
No permission remediation is part of this proposal.

## Candidate Docker API boundary

Evaluate a host-side Docker authorization plugin, not a proxy that leaves the
original socket accessible. Docker documents request/response authorization at
its daemon HTTP boundary:
[Docker authorization plugins](https://docs.docker.com/engine/extend/plugins_authorization/).
This is a candidate, not a claim of compatibility with Tower or comprehensive
container restart inhibition. Check installed daemon version, existing authorization
plugins and live-restore configuration before implementing or planning deployment.
An existing authorization policy must not be replaced or bypassed. The cited
page contains conflicting restart/loading statements; determine the supported
configuration/reload procedure for the installed Engine instead of assuming
that installation is restart-free. No daemon reconfiguration is authorized.

Docker explicitly excludes native gRPC and upgraded gRPC calls from this
authorization mechanism, and does not reauthorize established hijacked streams.
Those routes must be independently denied or shown unavailable in the accepted
deployment. A policy that only denies /grpc at HTTP request review is not proof
of native gRPC exclusion. Until that gap is addressed, this candidate cannot
establish the complete daemon control boundary.

The intended maintenance policy denies operations capable of starting/recreating
writers, exec/attach streams, filesystem writes and control/policy changes. Permit
only explicitly reviewed observation routes; GET alone is not an adequate
allowlist, because some routes upgrade/hijack connections or expose streams.
Unknown method/path/version/body and policy-state uncertainty must deny. No
universal owner header/token or root-user exception may bypass the policy.
The future controller cannot depend on denied Docker API calls to recover itself.

This leaves the web interface reachable while Docker actions may return an
explicit maintenance denial. It does not promise every Docker page remains
fully functional. Actual compatibility and legitimate non-Docker management
availability require an isolated integration rehearsal before production use.

## Limits that remain separate blockers

- API authorization does not itself stop already-running writers, revoke open
  exec/attach streams or establish container mount coverage.
- Automatic container restart, daemon startup/live restore, pending requests and
  Unraid autostart must be evaluated separately. The accepted process-failure
  fixture does not cover daemon/host restart. All relevant writers must be
  quiescent before any authoritative baseline is collected.
- NFS service dispatch and pending client writes need their own fence and recovery
  sequence. No Docker plugin result grants NFS ownership. Existing Mac v3 evidence
  cannot stand in for untested protocol routes.
- A host administrator can alter daemon configuration or bypass a shell wrapper.
  Define the trusted administrative boundary explicitly; do not advertise a
  plugin as protection against arbitrary host-root control.
- A controller crash must retain a deny state, not trigger timed expiry or automatic
  restoration. Durable state loading and boot order must fail closed before any
  media execution. Reboot diagnostics never grant automatic retry or clearance.

## Delivery sequence and approval boundary

1. Read installed daemon capabilities/configuration identifiers only; do not
   dump daemon options, environment variables, credentials or container config.
2. Implement and exercise the candidate in a separate disposable daemon/control
   environment. An ordinary client connected to Tower's daemon is not isolation.
   Determine whether available resources can support this without kernel/module
   changes or production daemon access. If not, report that limit before installation.
3. Review explicit request rules, durable-state/crash handling, startup ordering,
   availability effects, NFS coordination, backup and rollback artifacts together.
4. Obtain approval for the concrete installation/restart/rehearsal package only
   after those artifacts exist. No current design answer authorizes that step.
5. Accept actual adapter + verifier + recovery integration before closing Gate 6.

If the daemon boundary cannot meet the availability and fail-closed requirements,
revise the architecture rather than relaxing media protections or installing an
untested guard on Tower. This proposal removes no production cutover blocker.


## Installed baseline and offline policy increment

Tower reports Engine 29.8.2, authorization plugins null, live restore false.
These observations do not establish request fencing or future restart behavior.
No daemon reload, signal, setting change, plugin installation or service stop
was performed. The dockerd reference explicitly lists authorization plugins as
a reloadable setting; that resolves the generic reload capability, not Tower's
configuration integration or uninterrupted enforcement during a policy change:
[dockerd reload behavior](https://docs.docker.com/reference/cli/dockerd/#configuration-reload-behavior).

`app/sqlite_docker_maintenance_policy.py` is an offline always-maintenance
candidate rule function, with Docker AuthZ response keys. It has no listener,
installer, daemon calls, inactive mode, owner header exception or production
caller. Only exact unversioned ping/version/info/container-list observations
are allowed. Versioned endpoints remain denied until independently rehearsed;
this is deliberately not compatible with ordinary full Docker CLI/UI operation
yet. Mutations, streams, upgrades, body framing, ambiguous query/path encodings
and missing metadata deny. Results never echo caller credentials or URIs.

Local tests exercise these rules only, not daemon enforcement. Local Docker
Desktop separately reports Engine 29.8.2 via its explicitly selected local Unix
socket. A read-only image inventory found no cached Docker-in-Docker runtime.
The existing local daemon was not reconfigured and must not be used as the
experimental authorization target. No image was pulled or built. A separate
daemon rehearsal remains necessary; mocked AuthZ responses are not a substitute.


## Separate-daemon HTTP rehearsal completed

The subsequent [local separate-daemon rehearsal](sqlite-docker-authorization-rehearsal.md)
used official Engine 29.8.2 in a new network-isolated container, without
privileged mode or host Docker/media mounts. Only that nested daemon loaded the
private fixture endpoint. Status reads returned 200, mutation/stream requests
returned 403 and plugin death made a create request fail with 500. All new
fixture containers/volume were removed. This supersedes the earlier statement
that no runtime was pulled: the official dind image was fetched for this test;
no image was built. The host/local daemon configuration was not changed.

This is bounded HTTP enforcement evidence, not complete Docker writer exclusion,
Unraid UI compatibility, NFS coordination or restart/boot acceptance. The policy
remains deliberately uninstalled on Tower.


The candidate's empty private daemon now additionally has local restart/plugin
loss acceptance: policy remains active after that container restarts, and missing
plugin validation prevents its next startup. This does not establish continuity
while changing daemon configuration, restoring existing writers, loading a durable
maintenance hold or booting Unraid. The launcher rejects non-Docker-Desktop outer
engines before creating resources; do not run it on Tower.


The private candidate now requires a fixed persisted deny-only hold. Its explicit
fixture reload can restore only that deny service, never media-work authority.
Missing/corrupt/drifting evidence denies all protocol requests including plugin
activation. Local separate-daemon tests accept unchanged-hold reload and corrupt
hold startup denial; they do not accept a production fence activation or release
sequence, host boot recovery, existing writer exclusion or NFS coordination.


The private candidate now prototypes reduction-only quiesce requests for a
persisted full-container-ID scope: stop or exact restart-policy no, with all
other control mutations still denied. No production controller consumes this
policy. Local empty-daemon routing proves filtering before/after scope reload,
not actual writer quiescence. An initial production design must still establish
a complete fresh inventory, verify disabled automatic restart and stopped state,
and bind that evidence to the accepted media ownership boundary.


An independent disposable Linux VM now has successful actual-writer acceptance
for the candidate: restart-disable, stop, selected-ID state inspection and no
resumption after the private daemon restarts. Its own kernel avoided privileged
nested workloads on a shared Docker Desktop kernel. No Tower changes occurred.
See the guest rehearsal for exact scope; the complete production ownership model,
boot routes, NFS and integrated SQLite verifier/recovery remain unaccepted.


## Next host observation: actual listener routes

The guest boot prototype now has real valid-hold/corrupt-hold reboot and policy
process-death acceptance; see [its evidence](sqlite-docker-boot-guest-rehearsal.md).
It is not an Unraid installer. The next host-adapter input is a fresh listener
snapshot, since HTTP authorization cannot establish native gRPC exclusion.

Run only in Tower's host terminal:

```sh
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  bash scripts/sqlite_control_transport_probe.sh
)
```

The probe queries TCP/Unix listeners with `ss` and prints rows attributed to
Docker, containerd or BuildKit. It does not connect to those sockets, query the
Docker API, display process command lines/environment, change permissions,
reload/start/stop anything or load modules. Missing process names are unknown
visibility, not evidence of no listener. It explicitly rejects a Docker-container
execution context. The host snapshot is one architecture input, never an
ownership permit, full namespace inventory or proof that existing streams have
been revoked. No production changes are authorized by running it.


## Tower listener snapshot accepted (2026-10-23)

The host probe returned `listener_snapshot_complete`. No TCP listener with a
visible dockerd/containerd/buildkitd attribution was observed. This is not proof
that every TCP or namespace route is absent. Observed Unix paths included:

- `/var/run/docker.sock` attributed to dockerd;
- `/var/run/docker/containerd/containerd.sock` and its `.ttrpc` sibling;
- `/var/run/docker/containerd/containerd-debug.sock`;
- Docker metrics and libnetwork sockets.

The output also included `/var/run/emhttpd.socket` with many associated processes,
including dockerd/containerd. `ss` process attribution is not exclusive service
ownership: that shared management listener must not be classified as a Docker
control API or fenced merely because those names appear on the row. No management
socket change is proposed. Process IDs and per-run libnetwork identifiers are
transient observations, not configuration bindings.

Native containerd access is a separate runtime control boundary, not a route
protected by the Docker HTTP authorization policy. Its upstream
[security threat model](https://containerd.io/docs/main/security/threat_model/)
treats privileged runtime socket access as root-equivalent. The
[operator guidelines](https://containerd.io/docs/main/security/operator_guidelines/)
call for restricted socket ownership/access. These facts do not establish Tower's
actual permissions, ACLs, namespace/bind exposure or existing connections. Do not
chmod/remove/rebind any observed socket based on this inventory alone.

The next adapter requirement is explicit access coverage: ordinary Docker API
clients remain subject to AuthZ, while direct runtime access and privileged host
administration must be covered by a reviewed access/trust boundary. No plugin
claim may silently absorb these routes. Existing client streams and administrative
configuration changes remain separate. No listener snapshot grants ownership.


## Tower runtime permissions accepted (2026-10-23)

The host reports `/var/run/docker` and `/var/run/docker/containerd` as UID/GID
0:0 directories, mode 0700. The containerd gRPC, ttrpc and debug sockets are
0:0 mode 0660. Supplied ACL output contains only the base user/group/other entries.
Docker's public Unix API socket is separately UID 0, GID 281, mode 0660.

For ordinary pathname lookup without privilege, the root-only parent directories
restrict traversal to the containerd sockets. Thus the earlier guest experiment
proves a route for an already socket-authorized caller; it must not be described
as evidence that unprivileged Tower dashboards can reach containerd. No chmod or
runtime shutdown follows from this snapshot. Group membership, privileged users,
capabilities, bind-mounted sockets/parents, alternate aliases, inherited handles
and namespace exposure still require scoped review. Existing connections are not
revoked by metadata observations.

The advisory container reviewer now also flags source mounts overlapping declared
runtime control directories, including parent-directory mounts and read-only
binds, and recognizes `.sock.ttrpc` sockets. Stopped containers remain in scope.
This closes a reviewer omission; a host path's mode cannot be applied blindly to
a socket separately bound into a container. Paths are lexical declarations, not
resolved physical aliases. Defaults cover common `/run` and `/var/run` runtime
paths; the Python CLI accepts additional `--control-root` aliases, so deployment
paths are not restricted to Tower's layout. Reports grant no enforcement permit.


## Updated selected container review accepted (2026-10-23)

The report observes 22 containers and flags 11 for advisory review:

| Declared route | Observations | Required design treatment |
| --- | --- | --- |
| Writable media mounts, running | Auditor, Jellyfin, audiobookshelf, NZBGet, Sonarr, Radarr | Cover actual write scope and starts; the current auditor is itself a writer and cannot supply its own independent maintenance boundary. |
| Writable media mounts, stopped | MakeMKV (privileged/devices, restart always), Lidarr (unless-stopped) | Preserve stopped state and inhibit starts; stopped is not excluded. Elevated access needs separate review. |
| Docker API mounts | Homarr and Homepage, both read-only socket binds | HTTP access remains administrative; read-only binds do not make API requests read-only. Homepage also has a read-only media bind. |
| Unresolved volume | SearXNG cache volume | Resolve scope; this observation alone is not a declared media write or a reason to stop the service. |

Jellyfin has both native and shfs media sources, including nested writable Movie
and TV mounts. A read-only parent alone would not cover these. The supplied
review does not flag a declared runtime control-directory bind or a host-PID
route; no physical alias or complete elevated-access exclusion follows from that
absence. The privileged stopped container remains a distinct control concern.

The media roots for this snapshot cover the entire share. Podcast/download/cache
mount classifications must not be converted directly into a list of services to
stop for a Movie/TV operation: narrow operation scope and actual aliases must be
resolved first. None of these names is a stable full-ID execution binding, and
this report must not be fed to a quiesce executor as authority. No container is
stopped, remounted, restart-updated or otherwise changed by this acceptance.
