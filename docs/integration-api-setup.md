# Integration setup

Administrators can open **API setup** in the sidebar (`/integrations`) for
readiness information and copyable URLs. Integration settings are saved under **Settings → Integrations**. Generate or enter a token with 32–256 ASCII letters,
digits, underscores, or hyphens. A URL-safe random token is suitable. Keep it
separate from Jellyfin/Arr keys and browser administrator credentials.

For title widgets, enable **API Title Lists**. Optional **API Artwork Links**
enriches supported lists with artwork/navigation metadata. **API Coverage** exposes
aggregate folder/date coverage. Apply changes without restarting the container.
Each option is independent. Read [the API contract](integration-api.md) before
exposing data on a shared dashboard.

## Homarr source and query

1. Select an HTTP API source with the auditor's base URL, such as
   `http://SERVER:8089`. Use the published host port; `8080` is the default
   internal container port. Use the URL reachable from Homarr's container.
2. Select Bearer authentication and enter the token alone in its credential field.
3. Create a GET request named `titles` with Path `/api/v1/titles/leaving-soon`.
4. Under query values, add `library` with a literal value of `Movies` or `TV`.
5. Use the matching [widget template](integration-widgets.md), then Test/preview.

The TV title endpoint lists whole-show Holding records. Staged individual seasons
are displayed in the auditor dashboard and are not currently returned by that
widget endpoint.

## Troubleshooting

| Result | Check |
| --- | --- |
| 401 | The Bearer token matches the current auditor, with no extra prefix or whitespace. |
| 404 | API token configuration is valid and the route's required opt-in is enabled. |
| 503 | Tracking or service observations are unavailable; preserve the error instead of displaying zero. |
| External request failed | Source URL, duplicated `http://`, private-network access, and container reachability. |
| Empty list | The selected library has saved whole-title records in that stage. |

A successful browser visit does not prove Homarr can reach the same address.
`localhost` in a dashboard container refers to that dashboard container. Saved
tracking can be empty after new initialization even when media folders exist;
preview scans do not persist discovery dates. A live scan records eligible new
clocks. Avoid resetting existing dates to populate a widget.
