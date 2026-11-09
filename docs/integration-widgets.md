# Dashboard widgets

The release includes read-only authenticated API examples for Homarr and Homepage.
Configure the auditor API first using [Integration setup](integration-api-setup.md).
Templates contain placeholders; credentials belong in the dashboard's server-side
credential configuration, never in committed JSON, JSX, URLs, or browser code.

Use an auditor address reachable from the dashboard container. `localhost` refers
to that container. The example host port is 8089; use your actual mapping. Board
viewers can see returned collection information even when the Bearer token stays
on the dashboard server.

## Available examples

All files are under [examples/integrations/](../examples/integrations/).

| Example prefix | Data |
| --- | --- |
| `homepage-services` | Homepage Custom API summary and worker-status services. |
| `homarr-widget` | Homarr summary/status definition. |
| `homarr-oldest-waiting` | Up to ten oldest whole-title Waiting records. |
| `homarr-leaving-soon` | Whole-title Holding records across libraries. |
| `homarr-tv-leaving-soon` | TV whole-show Holding records. |
| `homarr-oldest-waiting-compact` | Compact oldest-Waiting presentation. |
| `homarr-movies-leaving-soon-compact` | Compact Movies Holding list. |
| `homarr-tv-leaving-soon-compact` | Compact TV whole-show Holding list. |

Homarr title examples have matching `-widget.example.json`,
`-requests.example.json`, and `-template.example.jsx` files. The complete widget
file is for import; request and JSX fragments support manual workbench setup.

TV Leaving Soon API lists are whole-show tracking lists. The auditor dashboard's
separate **Seasons Leaving Soon** group is not currently represented by these
widget endpoints. Dates estimate stage transitions rather than promising deletion.

## Homarr Custom Widgets v2

Use an installed version with the Custom Widgets v2 workbench.

1. Import a complete definition or create one under Management → Custom Widgets.
2. Configure its `default` HTTP source with the auditor's base URL, matching
   network scope, and Bearer authentication. Enter the token alone in the source
   credential field.
3. For manual entry, use the corresponding requests fragment and JSX template.
   Each independent title widget uses request ID `titles`.
4. For library-specific lists, keep Path `/api/v1/titles/leaving-soon` and put
   `library=Movies` or `library=TV` in **Query/body/behavior → Query values**.
   In a manifest this is the request's `query` object, not part of `path`.
5. Run Test/preview and schema validation before saving to a board. The examples
   use zero request-cache duration; configure the desired board refresh, such as
   60 seconds, and check installed-version cache behavior.

The examples render loading, error, empty, and truncation states explicitly.
Null counts remain unavailable rather than becoming zero. Title templates use
fixed slots up to the API's ten-record limit. Compact rows use smaller artwork,
stage/library labels, and minute-precision dates. Missing artwork has a fallback.
Matched artwork links open Jellyfin. The dates preserve API local wall-time
characters without browser time-zone conversion.

Artwork metadata requires `INTEGRATION_API_MEDIA=true`, and title routes require
`INTEGRATION_API_TITLE_DETAILS=true`. Browser image loading also depends on the
artwork URL being reachable by the viewer. An API success alone does not verify
that route, reverse proxy access, or the user's Jellyfin session.

The examples were reviewed against specific Homarr source revisions and exercised
with manually configured movie widgets. This is narrower than a compatibility
guarantee for every Homarr release or every complete-definition import. See the
[pinned compatibility notes](integration-widget-version-review.md).

Upstream documentation covers [request/security configuration](https://homarr.dev/docs/management/custom-widgets/requests-and-security/),
[authoring](https://homarr.dev/docs/management/custom-widgets/authoring/), and
[the JSX runtime](https://homarr.dev/docs/management/custom-widgets/custom-jsx/).
Check the workbench shipped by your installed version.

## Homepage

Merge [`homepage-services.example.yaml`](../examples/integrations/homepage-services.example.yaml)
into your existing `services.yaml` and replace the placeholder auditor URLs.
Set `HOMEPAGE_VAR_AUDITOR_TOKEN` privately in Homepage's deployment. The quoted
placeholder is Homepage substitution syntax, not a value to replace with a secret
in the committed example.

The Custom API widget uses GET requests, list display, and a 60-second refresh.
Text/null mappings preserve missing versus zero values. Labels identify the
counts as saved records with unverified freshness. Records in multiple sections
must not be added into a unique-title total.

Check error and stale-value behavior in the installed dashboard. A proxy should
preserve API errors instead of converting 401/404/503 responses into successful
empty objects. See [Homepage Custom API](https://gethomepage.dev/widgets/services/customapi/)
and [environment secrets](https://gethomepage.dev/installation/docker/#using-environment-secrets).

## Validate your setup

| Observation | Expected result |
| --- | --- |
| Synthetic counts | Values agree with the fixture. |
| Empty valid list | Empty message or zero count. |
| Wrong token | Authentication error. |
| Unavailable state (503) | Unavailable/error state. |
| Failure after a successful refresh | Failed refresh remains visible; stale data is not presented as current. |
| Missing dates/artwork | Explicit unknown/fallback presentation. |
| More than ten matches | Truncation note and at most ten rows. |

Use the [expiring synthetic API fixture](integration-widget-lab.md) for visual
checks without production collection data. Synthetic HTTP tests verify the wire
contract, while installed-dashboard tests verify import, rendering, and polling.

## Development checks

Compact import files and editor fragments are synchronized by a generator:

```bash
python -B scripts/build_homarr_compact_examples.py --check
npm ci --prefix tests/homarr-render --ignore-scripts --no-audit --no-fund
npm test --prefix tests/homarr-render
```

To regenerate after an intentional template change, run the generator without
`--check`. Development-only JSX tests cover schema/library mismatches, loading,
errors, empty results, missing artwork, dates, links, and the row cap. Node and the
compiler are excluded from production images.
