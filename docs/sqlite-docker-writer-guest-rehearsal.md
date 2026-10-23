# Actual disposable writer: independent Linux guest rehearsal

Accepted locally on 2026-10-23 through `7140819`. This is not Tower deployment,
complete writer exclusion or Gate 6 closure. JSON authority, SQLite production
activation and deletion safeguards are unchanged.

## Independent test environment

QEMU 11.1.2 was already installed on the Mac. A new ARM Linux guest used two
virtual CPUs, 1 GiB RAM and a new 6 GiB sparse qcow2 overlay. It had its own kernel,
no host-directory sharing, no host Docker socket, no host raw/block devices and
no production media/configuration mounts. Only a loopback-bound SSH forward was
published, using a newly generated lab-only key and a private known-hosts file.
No existing SSH keys or configurations were modified. User-mode guest networking
was present; no bridge, production network interface or Tower connection was used.

The official Ubuntu minimal ARM image came from
[Ubuntu's release directory](https://cloud-images.ubuntu.com/minimal/releases/noble/release/).
Its downloaded bytes matched the official SHA256SUMS entry:

`11378ad399741da3884b4343a9b06c1a1bb3d8cb71e309a4a11cadc2b516d0f9`

The guest reported kernel 6.8.0-147-generic and Python 3.12.3. Docker 29.8.2
(build 8af9fe3), runc 1.5.2 and the runtime image were copied from the cached
local official Docker image. Only a new stopped extraction container was created
and removed on the local engine; no existing daemon was reconfigured. No image
build or package installation was needed. No Tower/Mac/Docker Desktop kernel
module or kernel setting was changed. This guest's root privileges were confined
to its separate kernel and virtual disk, not a privileged container on a shared
Docker Desktop kernel.

## Script and accidental-target guards

`scripts/sqlite_docker_writer_guest_lab.py` requires Linux root, the fixture
hostname and NoCloud instance ID, a new canonical root and no existing dockerd
process. These are accidental-target guards, not a security proof against host
root spoofing them. Do not run the script on Tower or use it as an installer.
Isolation came from the freshly booted VM and absence of shared host resources.
The script starts/stops only daemon/plugin processes it created and retains the
guest lab on failure; it never enumerates arbitrary containers to stop them.

The guest daemon had a private Unix socket, explicit new config/data/exec/PID
paths, vfs storage, no bridge/firewall/forwarding setup and no live restore. The
synthetic writer used network none and a new guest-local bind containing ticks.
It was a real running container, not an absent ID or simulated metadata record.

## Observed sequence

1. Load the cached runtime image into the guest's new private daemon.
2. Create/start a container with restart always, writing repeated ticks. Observe
   it past the 10-second restart-monitoring baseline and verify bytes increase.
3. Initialize the private authorization fixture with that actual full container
   ID in its persisted scope. Register its guest-local spec and reload only that
   newly created daemon. Require explicit start denial before proceeding.
4. Through the candidate, set restart policy to exactly no and stop the writer.
5. Inspect that same ID through its selected-ID observation route. Require
   Running false and restart policy no. Verify the synthetic bytes stop changing.
6. Restart the private guest daemon with the same config/data and active plugin.
7. Reinspect the writer, require it remains stopped/restart-disabled, verify
   explicit start still returns 403 and verify the bytes remain unchanged.

The candidate now allows GET inspection only for selected full container IDs.
It does not add broad container inspection, name/short-ID matching or arbitrary
GET access. No response bodies, environment variables or container IDs are
returned in the acceptance summary; only categorical checks are reported.

Actual result:

```json
{
  "status": "private_guest_writer_quiescence_complete",
  "baseline_writer_observed": true,
  "start_denial_verified": true,
  "restart_disabled_and_stopped_verified": true,
  "stopped_after_daemon_restart": true,
  "fixture_bytes_unchanged": true,
  "automatic_restoration": false,
  "fixture_only": true,
  "production_authorized": false,
  "production_activation": "disabled",
  "writer_exclusion_verified": false,
  "restart_inhibition_verified": false
}
```

The last two false fields mean complete deployment exclusion/restart coverage
has not been established. They do not negate the specific writer observations.
The test does not restore the writer's original always policy or start it again.

## Validation, cleanup and remaining scope

120 local candidate-policy/hold/transport/launcher/guest-guard regressions passed.
Those tests are separate from the real guest acceptance above; guard tests mock
host identity to check early rejection without controlling any service.

Selected guest-only logs/config/hold/scope evidence was saved under
`/tmp/mca-writer-vm.USFHhm/guest-evidence.tar`. The new guest was powered off and
QEMU removed its PID file. The temporary image/overlay/key/evidence directory is
retained for review, not committed to Git; it may be removed later as disposable
lab data. No test VM or extraction container was left running. No credentials,
images or guest disks were added to the repository.

This accepts one actual selected writer's quiescence and daemon restart behavior.
It does not establish complete live inventory/alias coverage on Tower, all host
or network writers, NFS pending writes, established streams/native gRPC, host
boot continuity, Unraid UI compatibility or integrated SQLite move/recovery
ownership. A matching ID/state snapshot alone remains advisory outside this
controlled fixture. The production maintenance adapter and full integration
remain blocked. Guest ext4/vfs is a test arrangement, not an application
filesystem requirement or a new filesystem-name restriction.
