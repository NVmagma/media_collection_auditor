# Host controller: runnable preparation core and bundle

Status: implemented preparation core; **not a production service controller or
approved host installation**. It has no service/mount/scheduler command, media
operation, release, adoption or recovery-clearance API. JSON tracking authority,
SQLite production activation and deletion safeguards are unchanged.

## Implemented behavior

`app/sqlite_host_controller.py` creates a new 0700 control directory containing
three 0600, single-link regular artifacts: a fixed preparation marker, an
exclusive controller lock and a maintenance request. Existing or partial
directories are refused; preparation never repairs or adopts them.

The request records a random request ID, process/session identity, actual Linux
boot/network/mount namespace, directory device/inode and unique mount identity.
The parent directory, artifacts and control directory are fsynced before a live
session is returned. Unsupported capabilities or sync failures never return a
session; partial state remains available for inspection.

The live handle checks its artifact bindings, permissions, owner, scope and
process identity. Any observed failure latches it unusable, including after the
environment is restored. Closing the handle releases only its advisory lock; it
does not delete or clear the maintenance request. That lock coordinates this
controller only and does not exclude media writers.

A separate review opens the existing lock without creating a missing lock and
refuses a live controller. It validates the retained request and reports changed
scope/session while keeping every action flag false. Its repeated artifact reads
reject observed drift. The report exposes no controller session token or raw
configuration. These checks are not continuous external-writer exclusion.

## Standard-library bundle

Build into a **new canonical absolute directory**:

```sh
python -B -m scripts.sqlite_host_controller_bundle --destination /absolute/new/controller-bundle
```

This is package preparation on the development machine, not an installation
command for Tower. The builder includes only six explicitly listed Python modules,
a fixed entry point and a hash manifest; it never collects environment files,
credentials or host configuration. It checks source identities again after
packaging and retains partial artifacts on failure. Output includes the entry
point and manifest SHA-256 values for review.

The bundle requires Python 3.12 or newer. Its supported invocations are:

```sh
python3 -I -S -B /absolute/controller-bundle/controller.py prepare --root /absolute/new/private-control
python3 -I -S -B /absolute/controller-bundle/controller.py prepare --root /absolute/new/private-control --hold
python3 -I -S -B /absolute/controller-bundle/controller.py review --root /absolute/existing/private-control
```

These describe the entry point; **no Tower control location has been approved**.
All invocations report blocked, with external actions, adoption and restoration
disabled. `--hold` retains the preparation lock and samples its bindings until the
process exits; it does not run an audit or stop services. There is no force/retry
option for an existing request.

`-I -S` avoids environment/user/site-package dependency loading. The entry point
validates its exact bounded manifest and every packaged source hash before
importing the controller. Symlinked, shared, nonregular, oversized or drifting
package artifacts fail. This checks package integrity under the accepted trusted
administrator model; it is not a signed release, hostile-root defense or atomic
code-load security boundary. A reviewed external manifest digest is still needed
for actual deployment.

## Real Linux acceptance

`scripts/sqlite_host_controller_container_lab.py --image FULL_CACHED_IMAGE_ID`
creates one new local container with a read-only image, private tmpfs, no network,
no host mounts, no Docker socket, no added capabilities and all capabilities
dropped. It does not pull or build an image. Its fixture builds the actual bundle
and runs the entry point with site packages disabled.

Acceptance passed using cached Python 3.12.15 image ID
`sha256:9c613e2f963adb5c2c80cf1f51c7c58ebc78bbe75016af1076d3e90c4cc58def`:

- actual controller SIGKILL;
- live lock conflict refused in another process;
- exact request/marker/lock bytes retained after death and review;
- fresh process/session recognized and adoption refused;
- replacement preparation rejected without overwriting the retained directory.

This is actual Linux process/scope/lock behavior, not mocked boot identity, but
it runs inside a disposable container. It does not establish native Tower scope
or prove Docker shutdown survival of this particular bundle. Tower's separately
accepted exported interpreter mechanism remains the deployment starting point.

## Host integration still required

The accepted exported runtime has no host `/proc` or production control mapping.
This core therefore cannot simply be copied into it and declared operational:
missing Linux scope must fail rather than substitute caller-provided scope.
A reviewed launcher needs narrowly scoped read-only observation access, a private
persistent control mapping and immutable code, while preventing accidental access
to production media, administrative sockets and writable host settings. Namespace
observations inside a chroot/container are not by themselves native host binding.

Control ownership/mode checks do not prove that a path is outside every NFS/SMB
export, Docker bind, pool/user-share alias or other writer's access. That location
review and capability verification remain mandatory. No default under media,
appdata or `/mnt/user` is silently selected.

Actual Unraid service/settings adapters, boot fencing with automatic storage
startup, fresh Jellyfin protection availability, explicit owned-change recovery
and production ownership-bound operations remain unimplemented. The preparation
report includes fixed blockers for these dependencies; an operator boolean cannot
turn a successful preparation into permission to act.

## Native launcher candidate

The [native preparation launcher](sqlite-host-controller-native-launcher.md) now
runs the copied runtime through its own loader, avoiding chroot and host proc/control
bind mounts for this preparation core. Local ARM64 Linux launch, mapped-runtime,
SIGKILL and review acceptance passed. x86-64/Tower acceptance and actual private
control location/runtime deployment review are still pending. The chroot mapping
requirements above describe that alternative design; no such mappings were added.
