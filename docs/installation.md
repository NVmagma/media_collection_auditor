# Install and update on Unraid

Media Collection Auditor is deployed using its Unraid Docker template. Configure
service connections, lifecycle rules, safety controls, paths, notifications and
read-only API access in the application's Settings. No environment file is used.

## Add the template

Use the maintained [Unraid template](../unraid/template/media_archiver.xml) with
Unraid Docker → Add Container. The template pins the accepted image; use
`ghcr.io/nvmagma/media_collection_auditor:stable` in Repository if you prefer the
promoted stable tag. Candidate images are for testing.

Set only the deployment details in Unraid:

| Template field | Purpose |
| --- | --- |
| Web UI Port | Host port mapped to container port 8080. Choose a free port. |
| Auditor Logs | Persistent private appdata mounted at `/app/logs`. Use a new empty directory for a fresh install. |
| Media Library Root | Native filesystem root mounted at `/media`, for example `/mnt/POOL/media_storage`. Select your actual pool path. |

The template uses a read-only container root, no-new-privileges, and drops all
capabilities except DAC_OVERRIDE so the worker can manage host-owned media.
Keep these settings and both persistent mounts when recreating the container.
Do not expose the administration service directly to the public internet.

## First start

1. Start the container. A **new empty appdata directory** initializes JSON state.
2. Click the container icon → WebUI. Open Unraid's container logs and copy the
   one-time setup code into the setup page. This code authorizes creating the
   administrator; keep the logs private while setup is pending.
3. Create a local administrator with a password of at least 12 characters. Only
   its password hash is saved. The setup code becomes unusable after completion.
4. Sign in and open **Settings → Connections**. Enter Jellyfin, Radarr and Sonarr
   addresses and API keys, Apply Requested Settings, then test saved connections.
5. Configure enabled libraries, paths, schedule/time zone and retention settings.
   New installs stay in Dry Run, with permanent deletion, season retention and
   metadata quarantine disabled. Review preview results before enabling live work.

Session signing keys are generated automatically and retained in appdata. Change
the local account under **Settings → Account**. Jellyfin users can sign in after
its connection is configured; only administrators can change settings or run scans.
Enable **Settings → Web → HTTPS-only Login Cookie** when using an HTTPS reverse
proxy. It prevents subsequent login through plain HTTP.

Initialization never repairs or replaces existing appdata. Missing/corrupt state
in a nonempty directory pauses scans for review. A partial first initialization
requires investigation; do not delete existing tracking to make setup appear.

## Media folders

Create all stages of each enabled library under the native root:

```text
media_storage/
├── Movies/
├── Movies_hold/
├── Movies_keep/
├── Movies_removal/
├── TV/
├── TV_hold/
├── TV_keep/
├── TV_removal/
└── TV_seasons_leaving_soon/   # Optional season retention
```

The worker does not create missing lifecycle roots. Under **Settings → Paths**,
optional absolute container paths override this layout. Paths must stay on the
same native mount/device for atomic moves. Do not bind Unraid's `/mnt/user` FUSE
view or add a child mount over a stage; they can prevent the required no-overwrite
rename. Keep appdata separate from media.

Jellyfin and Arr must see the corresponding folders. Optional Arr aliases for
non-Waiting stages are also configured under Paths. Whole-title Removal deletion
currently requires identical local and Arr Removal paths. Configure Jellyfin
Leaving Soon libraries separately if the family should browse Holding media.
See [season retention](tv-season-retention.md) for individual seasons.

## Upgrade an existing installation

Create a private backup under **Backups**, wait for active work to finish, and
review pending operations. Pull the updated image in Unraid and apply it with the
same mounts and port. Verify the WebUI, settings, tracking and a recorded scan.
Never initialize or replace existing appdata during an update.

Existing saved settings remain authoritative. Old template variables are accepted
as a migration fallback. While those variables still exist, open Settings and
apply each reviewed value so it is saved in appdata. Under Account, establish the
local administrator account before removing its old template password. Then
remove obsolete application variables from the saved Unraid template, retaining
the port, mounts and security parameters. The app no longer loads environment files.

Use only one worker against an appdata directory. Saved live/deletion settings
survive updates; image defaults do not reset prior choices. Keep one current
saved template for the container so an old duplicate cannot restore obsolete mounts.
Backups do not undo moves or restore deleted media. See [backups](browser-backups.md)
and [operation recovery](arr-intent-recovery.md).
