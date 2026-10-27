# Integration setup and readiness

Administrator browser sessions can open `/integrations` from Settings or the
Dashboard. The page shows token configuration (never its value), selected tracking
readiness, title/poster options, copyable connection coordinates, movie/TV queries,
and error and token-replacement instructions. The browser origin is a suggested
base URL; it does not prove reachability from Homarr or Homepage. Copy controls
fall back to selecting the text when clipboard access is unavailable over HTTP.

`GET /api/v1/readiness` uses the same dedicated Bearer token as summary/title
routes. It returns API/schema versions, supported routes/libraries, tracking
availability and preview binding status. It does not collect Jellyfin, Arr or
filesystem inventory, claim freshness, expose titles/paths/tokens, or authorize
media actions. A valid token is required even when the preview binding is paused.
Unavailable tracking or binding returns 503, never an empty successful result.
API-only services report coordinator scope unavailable.

Authenticated unknown v1 routes return `route_not_found`; unauthorized callers
still receive the existing auth response first. Existing route response contracts,
unsupported method handling and disabled-title behavior remain compatible.
All integration responses and the administrator setup page use no-store caching.

Token rotation remains a container environment operation. The page documents
local random generation and replacing INTEGRATION_API_TOKEN in the existing
reviewed Unraid template, preserving its mounts, image, flags and settings.
After recreation the old token is rejected; widgets must use the new token.
The page neither displays nor changes secrets, settings, state or services.

## Additional useful APIs to consider

- Scan observations: bounded process-local history and proposal counts, with
  unknown counts and restart scope explicit.
- Backup status: last verified backup receipt and age without private paths or
  contents. This would require a defined trusted receipt source first.
- Notification delivery: opt-in redacted scan-failure/settings-review events,
  with destinations and retry policy explicitly configured.

These are future proposals, not new endpoints or authority to control media.

## Disposable visual review

The existing `scripts/dashboard_workspace_lab.sh` also serves `/integrations`
with synthetic status, no actual tokens and all POSTs refused. Use the running
fixture's URL plus `/integrations`. Production services are not connected.

## Library coverage endpoint

`GET /api/v1/coverage` requires the dedicated Bearer token and explicit
`INTEGRATION_API_COVERAGE=true`. It uses the same inventory and clock summary as
Review, with at most 10,000 directory entries per selected stage. Optional
`library=Movies` or `library=TV` limits both the inventory reads and counts.
Disabled libraries and duplicate/invalid library values return 400.

The fixed response has at most eight aggregate rows, never title names, absolute
paths, secrets or raw warning messages. Each row reports folder count, missing,
invalid and future dates, and tracking records without a matching stage folder.
The latter does not prove that a title was deleted. Unsupported/missing tracking
never falls back to empty state or JSON when SQLite is selected.

`complete=true` means all requested directories and tracking could be observed;
it does not certify live freshness, atomic filesystem state or action permission.
Unavailable directories return 503, retaining explicit unavailable rows with
unknown counts. Incomplete aggregate totals are null. Snapshot, settings or
source-identity changes invalidate the whole response. SQLite identity/revision
checks span inventory collection. This is an observation only: it writes no dates,
state, settings, media or service controls and makes no remote media requests.

Run `bash scripts/integration_coverage_lab.sh EXISTING_LAB_PARENT` on Tower after
updating the approved development checkout. It uses the cached auditor image only
as a Python/Flask runtime, current committed source, and newly created fixture
folders/state. Five actual loopback HTTP cases exercise auth/opt-in, filtering,
missing directories/state and source changes. No production mounts, host ports,
Docker socket, external connections or worker are used. Artifacts are retained.
