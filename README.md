# Media Collection Auditor

Manage Movie and TV lifecycles using Jellyfin tags, Radarr and Sonarr. The
serialized JSON worker keeps persistent tracking, clocks and scan history in
appdata. The dashboard, settings, APIs and operation recovery share that state.

## Current safety policy

- **Waiting:** new titles and their saved lifecycle dates.
- **Holding:** titles leaving soon.
- **Keep:** titles selected for retention.
- **Removal:** titles eligible for later review; moving here does not delete them.

`keep` selects retention; `keep-forever` protects the entire title and all seasons.
`not-at-all` selects early Holding. Jellyfin favorites are supported through
`FAVORITES_TRIGGER_KEEP`. `keep-all-seasons` is retained for TV protection policy.
Unknown Jellyfin protection blocks the affected title.

Removal deletion is disabled by default and requires explicit warning acknowledgement. Season pruning and cross-filesystem copy fallback remain unavailable.
Each live scan permits up to five Movie actions and five TV actions, with a total cap
of ten. Live scans start at least one hour apart, and overlapping scans are blocked.
Unlimited actions require a separate reviewed change.

## Dashboard and integrations

Left navigation provides the dashboard, separate collection Review, Activity Logs,
Settings, Integrations, existing-media Arr imports and operation recovery. Table
and poster views include current Jellyfin links. Activity and History distinguish
verified moves from proposals and uncertain outcomes. History persists across
restarts; the bounded display does not limit how many titles are scanned.

Daily scans use `DAILY_RUN_TIME` and `DAILY_RUN_TIMEZONE` (or `TZ`). Administrators
can confirm **Run Live Scan Now** or request a read-only preview. Apply Requested
Settings validates the current policy. Missing or corrupt settings/tracking pause
scans without initializing empty state.

Use `/api/v1/readiness`, `/summary`, `/audit-status`, title lists, coverage,
scan history, proposals and backup status with a dedicated Bearer token. API tokens
cannot start scans or change settings. See [API contract](docs/integration-api.md),
[setup](docs/integration-api-setup.md) and [Homarr examples](docs/integration-widgets.md).

## Unraid and Docker

Build with `docker/runtime.Dockerfile`. GitHub's JSON acceptance workflow tests the
exact image before optional publication to `ghcr.io/nvmagma/media_collection_auditor`.
Select its immutable published digest in the Unraid template's Repository field.
Keep the saved template consistent with the actual container to prevent updates
from recreating obsolete settings. The WebUI URL is `http://[IP]:[PORT:8080]/`.

Use two persistent binds:

| Container path | Purpose |
| --- | --- |
| `/app/logs` | JSON state, saved settings, history and pending-operation journal |
| `/media` | Native filesystem media root containing the four stages per library |

For Unraid, live atomic renames require a native filesystem path such as the
reviewed pool path, with all stage roots on one filesystem. Use port `8089:8080`
when preserving the existing installation. The root filesystem stays read-only;
the current reviewed runtime uses user `0:0`, drops all capabilities and adds
only `DAC_OVERRIDE`, with no-new-privileges enabled. No ownership changes are needed.

**Existing installation:** keep its current logs and media binds when updating the
image. Never initialize an existing directory or run two writers against it.

**New installation:** explicitly initialize an empty writable logs directory using
`python -B -m app.json_initialize` in the selected image, with no media mount or
network. The normal entrypoint refuses missing tracking rather than creating it.
Start in preview mode (`DRY_RUN=true`) and verify settings, stage paths, API access
and collected decisions before enabling live moves. Provide a strong
`WEB_SESSION_SECRET`, administrator credentials and private integration tokens.
Do not expose the administrative interface publicly without appropriate controls.

## Recovery and backups

A durable JSON intent is saved before a move, Arr update or import. Uncertain
operations pause scans and are never automatically replayed. Use Operation
recovery or Arr imports to collect fresh GET-only evidence and apply the reviewed
resolution. Preserve current clocks even when a remote acknowledgement was lost.

[JSON operations](docs/json-worker.md) covers state, backups, updates and recovery.
[Arr imports](docs/arr-existing-import.md) register existing folders unmonitored,
without download searches. [Recovery](docs/arr-intent-recovery.md) explains retained
move/sync outcomes. Repository cleanup does not delete retained host data or containers.

## Development

Work on `feature/interface-api` for the current changes; `feature/unraid` is the
project-default branch. Do not change `main` without explicit approval. Preserve
unknown tracking fields, protection checks and disabled deletion safeguards.

```bash
python -m pip install -r requirements.txt pytest
PYTHONPATH=.:app:tests WEB_SESSION_SECRET=synthetic-test-secret python -B -m pytest -q tests
docker build -f docker/runtime.Dockerfile --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" .
```

GitHub also checks Chromium navigation/settings, JSX widget rendering, real
loopback integration transports and disposable process-death recovery. The
optional Tower lab uses only new test directories and a disposable container:
`scripts/json_worker_lab.sh IMAGE_ID STATE_TEST_PARENT NATIVE_MEDIA_TEST_PARENT`.
Do not mount production data for disposable tests.

See the [roadmap](docs/feature-roadmap.md) and [branch workflow](docs/branch-workflow.md).

## License

See [LICENSE](LICENSE).

Removal-stage whole-title deletion is an opt-in feature described in [Removal deletion](docs/removal-deletion.md). It stays off until explicitly acknowledged in Settings.

The scanner detects metadata-only orphan folders. Optional [recoverable metadata quarantine](docs/orphan-metadata-quarantine.md) requires complete Arr/Jellyfin absence checks and 24 hours of unchanged observations. It is off by default and never deletes files.
