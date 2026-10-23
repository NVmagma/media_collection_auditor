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
