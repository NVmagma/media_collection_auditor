# Disposable boot continuity rehearsal

This is a separate-kernel Ubuntu guest experiment, not a host installer, Unraid
startup implementation or Gate 6 closure. Never run its preparation phase on
Tower. It requires the exact disposable guest identity and a previously marked
synthetic writer with a persisted deny-only hold. Production JSON authority,
SQLite activation and deletion safeguards are unchanged.

`scripts/sqlite_docker_boot_guest_lab.py` renders uniquely scoped service names
and rejects unsafe unit paths and existing target files. It installs only two
new services in the independent guest: a resumed deny-only authorization service
and the private Engine 29.8.2 service. Engine starts after and is bound to the
policy service. A bounded pre-start request must observe the policy's valid
activation response before Engine can start; Engine also validates its configured
plugin. Neither service automatically restarts. No production socket or mount is
used, no global Docker service is changed, and no NFS service is controlled.

The dependency model follows [systemd BindsTo with After](https://www.freedesktop.org/software/systemd/man/257/systemd.unit.html).
It is a prototype for the continuity requirement, not a claim that Unraid uses
systemd or that these units cover Unraid's emhttp/autostart routes. A future
Unraid adapter still needs separately reviewed host integration, availability
acceptance and explicit installation approval.

Preparation records the actual initial guest boot ID, selected synthetic writer
identity and digests of its deny hold and synthetic bytes. It enables the private
engine fixture for the next guest boot but does not reboot automatically. Checking
requires a different boot ID, active policy/engine, unchanged hold/media bytes,
a strict fresh stopped-writer observation and a denied explicit start. No matching
digest grants ownership or permission to resume media operations.

## Accepted real guest runs (2026-10-23)

- After an actual guest reboot, the boot ID changed, the policy and private engine
  were active, the selected writer remained strictly stopped/restart-disabled,
  its explicit start returned 403, and hold/media digests remained unchanged.
- SIGKILL of the policy's main process caused the bound private engine to stop.
  No dockerd remained and synthetic media bytes were unchanged.
- The fixture hold was deliberately corrupted without a repair/clearance step.
  A second actual reboot left both fixture services inactive/failed. The private
  engine socket was unreachable and synthetic bytes remained unchanged.

The `check-blocked` phase requires a separately recorded pre-corruption boot ID,
actual boot change, corrupt hold, unavailable services/engine and unchanged bytes.
It returns no clearance. Corruption is injected explicitly by the test operator;
there is no application repair or force-resume operation.

85 focused local checks passed. Their boot guards/unit rendering checks are not
substitutes for the guest reboots. Journal/unit/hold/media evidence was archived
to the host's temporary VM lab. Fixture units were disabled, corruption retained,
and the guest powered off. No Tower or existing host service was modified.

This accepts the prototype's boot dependency and failure behavior in this guest.
It does not establish Unraid boot ordering, availability of emhttp, NFS startup
fencing, complete administrative/gRPC/prior-stream coverage or the integrated
SQLite source-entry boundary. `writer_exclusion_verified` and
`restart_inhibition_verified` remain false for the deployment as a whole.
