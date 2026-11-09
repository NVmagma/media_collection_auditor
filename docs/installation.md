# Installation and updates

The supported deployment is Docker on Unraid with Jellyfin, Radarr for Movies,
and Sonarr for TV. Configure at least the services used by your enabled libraries.
The integration has been exercised with Radarr 6 and Sonarr 4. Python 3.12 is used
by the runtime and automated checks.

## Select the image

```text
ghcr.io/nvmagma/media_collection_auditor:stable
```

`:stable` is promoted explicitly to an accepted release. Versioned
`json-candidate-<revision>` tags are testing images. A digest reference can pin an
exact image for reproducibility. The maintained Unraid template at
[`unraid/template/media_archiver.xml`](../unraid/template/media_archiver.xml)
pins the accepted release digest; its Repository field can instead use `:stable`.

## Directory layout

Use one native filesystem root for media. With the default paths it contains:

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

All four stages of an enabled library must exist and be readable. Keep appdata
outside the media tree. `/app/logs` needs persistent writable storage.

On Unraid, bind the native path, for example `/mnt/<pool>/media_storage`, to
`/media`. Discover your own pool path rather than copying a pool name from another
installation. Unraid's `/mnt/user` FUSE view can reject the atomic no-overwrite
rename required for live actions. Paths on the same underlying disk can still
have different mount identities inside a container. Use the single `/media`
bind rather than adding a separate bind over a stage or season Holding folder.

Radarr, Sonarr, and Jellyfin need access to the corresponding folders. Arr-visible
path aliases can be configured through the `RADARR_APP_*_PATH` and
`SONARR_APP_*_PATH` environment settings for non-Waiting stages; whole-title
Removal deletion currently requires identical local and Arr Removal paths.
See [TV seasons](tv-season-retention.md) for the separate season staging folder.

## Initialize a new installation

Pull the image and create a new empty appdata directory. Substitute your own host
paths below. Keep `.env` outside the appdata directory until initialization finishes.

```bash
docker pull ghcr.io/nvmagma/media_collection_auditor:stable
mkdir -p /path/to/new/auditor_logs

docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --mount type=bind,src=/path/to/new/auditor_logs,dst=/app/logs \
  --entrypoint python ghcr.io/nvmagma/media_collection_auditor:stable \
  -B -m app.json_initialize
```

Initialization creates empty JSON tracking, settings, and scan-control metadata.
It refuses nonempty directories, including a partial initialization. Run this
only for a new installation. Starting the normal container with missing or invalid
state pauses the worker instead of creating an empty replacement.

## Configure and start

Copy [`env.example`](../env.example) to `.env` in your deployment directory and
fill in the service addresses and credentials. Restrict its permissions:

```bash
cp env.example .env
chmod 600 .env
```

Use a strong `WEB_SESSION_SECRET` and local `WEB_ADMIN_PASSWORD`. Configure
`JELLYFIN_HOST_URL` and `JELLYFIN_API_TOKEN` before using Jellyfin login. Set
`ENABLE_TV=true` for TV scanning. Start with `DRY_RUN=true`.

The following example uses the runtime image, a read-only container root,
no-new-privileges, and the minimum additional capability used for media owned by
another host UID. Match these settings in Unraid's container editor when using
the template.

```bash
docker run -d --name media_collection_auditor \
  --restart unless-stopped --read-only --user 0:0 \
  --cap-drop ALL --cap-add DAC_OVERRIDE --security-opt no-new-privileges:true \
  --env-file .env --publish 8089:8080 \
  --mount type=bind,src=/path/to/native/media_storage,dst=/media \
  --mount type=bind,src=/path/to/new/auditor_logs,dst=/app/logs \
  ghcr.io/nvmagma/media_collection_auditor:stable
```

Open `http://SERVER:8089/`. The Unraid WebUI template URL is
`http://[IP]:[PORT:8080]/`. The icon is available at
`/static/auditor-icon.png` through the static asset route.
Use Settings to test the saved Jellyfin, Radarr, and Sonarr connections, choose a
daily schedule and time zone, and review preview decisions. Saved settings override
the container environment. A preview does not persist new discovery clocks.
A live scan records discovery dates and performs only eligible enabled actions.

The web app uses Flask's built-in server. Treat it as a private administration
service. Use controlled network access and an HTTPS reverse proxy for remote
access. Set `WEB_SECURE_COOKIE=true` when browsers connect through HTTPS.

## Update an existing installation

1. Create a private backup under **Backups** and wait for any active scan to finish.
2. Review pending operations before replacing the container.
3. In Unraid, set Repository to `ghcr.io/nvmagma/media_collection_auditor:stable`,
   pull the image, and Apply with the existing media/appdata mounts and port.
4. Confirm the web interface, saved settings, daily schedule, tracking counts,
   and a recorded scan result.

Never reinitialize existing appdata. Run only one writer against a tracking file.
Saved live/deletion settings persist through updates, so a new image's safe
defaults do not reset an operator's previously saved choices. Keep the saved
Unraid template consistent with the container, including its Repository and mounts.
A duplicate old template for the same container can recreate obsolete settings.

A rollback to old tracking after live moves requires review of current media and
Arr state. Backups preserve dates and settings; they do not undo moves or restore
deleted media. See [backups](browser-backups.md) and [operation recovery](arr-intent-recovery.md).
