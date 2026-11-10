# Media Collection Auditor

Media Collection Auditor manages the lifecycle of movies and TV shows using
Jellyfin tags, Radarr, and Sonarr. It runs in Docker on Unraid and provides a web
interface for reviewing your collection, previewing decisions, and running scans.
Persistent JSON tracking preserves lifecycle dates, operation state, and scan
history across container updates.

## What it does

- Moves titles through **Waiting**, **Holding**, **Keep**, and **Removal** stages.
- Uses Jellyfin tags and favorites to select retention or early Leaving Soon.
- Stages older TV seasons with `one-season` and restores them with `keep-all`.
- Shows full shows and individual seasons separately in TV Holding, with posters.
- Provides daily and manual scans, live progress, searchable results, and history.
- Reviews unmanaged folders, stale tracking clocks, and metadata-only leftovers.
- Integrates with Homarr and Homepage through authenticated, read-only APIs.
- Offers private appdata backups and explicit recovery of interrupted operations.

## Safety defaults

**New installations start in Dry Run.** Whole-title deletion, TV season deletion,
season retention, and metadata quarantine are separate options that default to
off. Each deletion option requires its own warning acknowledgment in Settings.
Existing installations retain their saved settings when the image is updated.

Live scans share a one-hour cooldown and run one at a time. Each scan allows up
to five actions per library and ten overall, with a configurable lower total.
Whole-title deletions are limited to one per library per scan. TV season deletion
is limited to one season per scan within the same action budget.

Unknown or conflicting protection information blocks the affected action.
Interrupted operations retain a journal and can pause further scans. Filesystem
moves require atomic, no-overwrite renames on the same native filesystem mount.
Backups of tracking and settings do not back up your media files.

## Lifecycle and tags

| Stage | Purpose |
| --- | --- |
| Waiting | Incoming titles with saved lifecycle dates. |
| Holding | Leaving Soon, with a grace period before the next transition. |
| Keep | Titles selected for retention. |
| Removal | Whole titles eligible for deletion after a separate waiting period and safety checks. |

Apply tags to the individual movie or TV show in Jellyfin.

| Tag | Behavior |
| --- | --- |
| `keep` | Select the whole title for Keep. |
| `keep-forever` | Protect the title and all its seasons. |
| `not-at-all` | Select a title for early Holding. |
| `one-season` | With season retention enabled, retain the latest regular TV season and stage older seasons in Leaving Soon. |
| `keep-all` | Keep the TV show and restore its staged seasons. Overrides `one-season`. |
| `keep-all-seasons` | Existing all-season protection tag, also honored by season retention. |

Favorites can select whole titles for Keep through `FAVORITES_TRIGGER_KEEP`.
Favorites alone do not trigger season staging. Season 0 and Specials are preserved.
The latest season is the highest-numbered regular season with video files on disk.

## Install on Unraid

Use the published release image:

```text
ghcr.io/nvmagma/media_collection_auditor:stable
```

The web interface listens on container port **8080**. The installation example
maps it to host port **8089**. Two persistent mounts provide appdata and media:

| Container path | Contents |
| --- | --- |
| `/app/logs` | Tracking, saved settings, scan history, session key, backups, and operation journal. |
| `/media` | Native filesystem media root containing the lifecycle directories. |

[Installation and updates](docs/installation.md) covers template installation, protected first-run account setup, directory layout,
Unraid mount guidance, and existing-install updates.
Use a native pool path for live moves. An Unraid `/mnt/user` share or an extra bind
over one stage can prevent the required atomic rename even when files live on the
same physical disk.

Configure Jellyfin, Radarr, and Sonarr under **Settings → Connections**, then test
the saved connections. Inspect a preview before enabling live scans. Use a local
administrator or a Jellyfin administrator account for configuration and scan controls.

## Documentation

| Guide | Covers |
| --- | --- |
| [Installation and updates](docs/installation.md) | Fresh appdata, Docker, mounts, credentials, and `:stable`. |
| [Worker operations](docs/json-worker.md) | Scans, limits, tracking, progress, and history. |
| [TV season retention](docs/tv-season-retention.md) | Staging, restoration, grace periods, and optional deletion. |
| [Whole-title deletion](docs/removal-deletion.md) | Arr-managed deletion of expired Removal titles. |
| [Tracking Review](docs/tracking-review.md) | Clock mismatches, current Arr coverage, and clock archival. |
| [Metadata quarantine](docs/orphan-metadata-quarantine.md) | Recoverable cleanup of verified sidecar-only folders. |
| [Backups](docs/browser-backups.md) | Private snapshots, restore-copy testing, and limitations. |
| [Operation recovery](docs/arr-intent-recovery.md) | Interrupted moves, updates, imports, and deletions. |
| [Existing-folder imports](docs/arr-existing-import.md) | Register media unmonitored without download searches. |
| [Integration setup](docs/integration-api-setup.md) | API token, API setup page, and widget troubleshooting. |
| [API reference](docs/integration-api.md) | Routes, opt-ins, filters, and response semantics. |
| [Dashboard widgets](docs/integration-widgets.md) | Homarr and Homepage examples. |
| [Notifications](docs/operational-notifications.md) | Failure alerts and saved-destination tests. |
| [Dashboard](docs/dashboard-redesign.md) | Navigation, full-show/season views, and browser checks. |
| [Roadmap](docs/feature-roadmap.md) | Shipped work and remaining priorities. |

## Development and contributions

The release source is on `main`. See [CONTRIBUTING.md](CONTRIBUTING.md) for local
setup, testing, and pull request guidance, and [SECURITY.md](SECURITY.md) for
vulnerability reporting. Changes involving media operations need disposable-file
tests and must preserve tracking and protection safeguards.

The runtime is built from `docker/runtime.Dockerfile`. Deployment uses the Unraid
template; configure application options in the WebUI. No environment file, Compose
configuration, or manual initialization command is required for a new empty appdata mount.

## License

[GNU General Public License v3](LICENSE).
