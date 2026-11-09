# Dashboard and navigation

The released web interface uses shared left navigation for Dashboard, Activity
Logs, Backups, Tracking Review, Cleanup Review, Settings, and API setup.
Administrative actions require an administrator session.

## Dashboard workspaces

| Workspace | Contents |
| --- | --- |
| Overview | Collection totals, attention items, recent attempt summary, and short title lists. |
| Library | Movie/TV selection, lifecycle stages, search/sort, posters, and title details. |
| Review | A separate page for folder/date coverage and collection findings. |
| Scans | Current running/queued/blocked status and saved-date timer estimates. |
| Activity | Recorded observations and per-title outcomes. |
| History | Persistent attempts, filters, result pages, and recorded decisions. |

Library totals reflect folder observations; tracking totals reflect saved
records. Missing information is displayed as unknown. Search and sorting apply
to the rendered library snapshot. The Details panel explains the recorded stage,
clock, and available protection information. It supports keyboard close/focus
behavior and stacks on smaller screens.

TV Holding separates **Full Shows Leaving Soon** from **Seasons Leaving Soon**.
Both groups support table and poster view. Season cards use the show's Jellyfin
artwork and show the season number, staging date, and grace-period end. The
search results line counts shows and seasons in that stage. The Holding tab's
badge continues to count whole-show folders; the two group headings have their
own counts.

## Settings

**Apply Requested Settings** validates and saves the form for the next scan. A
running scan uses its captured settings. Connection and notification test buttons
use saved values. Secrets are not placed in draft markers or browser storage.
Destructive settings require their displayed warning acknowledgment.

## Automated UI verification

GitHub's [Python safety workflow](../.github/workflows/python-safety.yml) renders
synthetic inputs and runs Playwright Chromium checks at desktop and mobile widths.
It covers navigation, stages, table/poster switching, filtering, literal special
characters, inspector focus, and overflow. Development-only Node dependencies are
excluded from the runtime image. Use the commands in that workflow for a complete
local browser check.

## Optional disposable visual preview

On a Linux Docker host with a container named `media_collection_auditor`:

```bash
mkdir -p /path/to/new/ui-labs
bash scripts/dashboard_workspace_lab.sh /path/to/new/ui-labs 8091
```

Run from the committed checkout matching the UI you want to preview. The helper
uses the installed image's cached Python dependencies, creates a new fixture
container, and publishes the chosen unused port for fifteen minutes. It mounts
synthetic source only. It neither mounts production media/appdata nor starts the
auditor worker. The fixture exposes a limited preview surface rather than a full
production deployment. The printed address uses the original lab server address;
substitute your own host IP if needed. The exact returned container ID and lab
directory identify the disposable resources.
