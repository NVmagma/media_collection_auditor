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
