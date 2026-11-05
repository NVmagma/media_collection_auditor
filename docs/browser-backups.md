# Browser backups

Administrators can open **Backups** in the sidebar. **Create private backup**
explicitly captures the current JSON state and saved settings under the shared
writer lock. A running scan/settings writer blocks capture rather than queuing a
retry. Saved clocks, worker claims, pending intents and unknown fields are copied
unchanged. Media, action/history logs and external services are not backed up. Environment-only
credentials, container options and Unraid templates are not captured.

Private copies include saved credentials. They live under `.auditor-backups` in
the existing Auditor Logs mount with owner-only directory/file permissions. This
is appdata storage, not off-server protection: copy a verified whole packet to
separate protected storage for disk-loss protection. No backup contents are
returned in the browser. Previously created host packets and the integration
API's explicit pinned selection are not searched, adopted or changed.

Each displayed packet is checked against its recorded directory identity, receipt
fingerprint, payload hashes and JSON schema. Incomplete or changed packets remain
visible as unverified; they are not repaired or replaced automatically. Browser
snapshots use `browser-selection.json` alongside the private receipt and payloads.
Keep all of those files together when copying a packet off-server.

**Test restore copy** explicitly creates a new private disposable directory in
`.auditor-backups/.restore-tests`, copies both payload files, compares their bytes,
and records a completion receipt only after revalidating the selected source.
This tests copy/integrity and retains original clocks/settings/unknowns. It is
not a running-service recovery test and never starts a worker, configures a
container, contacts Arr/Jellyfin, changes active files, clears an intent or replays
a media operation. Pending operations stay pending in the copy. Do not start a
worker against a test copy: its settings can contain live policies and credentials.

Interrupted copies are retained without a completion receipt and are never
resumed automatically or overwritten. There is no active restore or purge
control. Up to 100 browser packets and 100 test copies are retained, with no
automatic retention deletion; reaching the bound requires manual review. Plan an
actual production restore separately, with services stopped and current media/
Arr outcomes reviewed before adopting any historical state.

A packet copied to another directory or disk has a new directory identity. Keep
its original receipt/fingerprint; adoption at the new location requires explicit
verification during the separate recovery plan. The browser does not silently
rebind relocated snapshots or start a worker from them.

## Packaged recovery rehearsal

The JSON worker acceptance workflow creates a backup and a test copy through
the administrator interface using synthetic settings and media. It starts the
packaged service against that disposable copy and checks authenticated tracking
counts, restored settings and the saved scan cooldown. A separate history path
reflects the scope of the backup. The fixture compares the original and copied
files after shutdown and checks the mock services for any additional requests.

For the same rehearsal on Tower, use the [isolated JSON worker lab](../scripts/json_worker_lab.sh)
with an image built from the fixture checkout's revision. The lab uses new state
and media directories and runs in a container with networking disabled except
for internal loopback.
