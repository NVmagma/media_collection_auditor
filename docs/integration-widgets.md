# Dashboard integration examples

These are opt-in configuration examples, not a deployment step or a promise that
the installed dashboards support the latest upstream format. They were checked
against upstream documentation on October 22, 2026; no Homepage/Homarr instance
has rendered them yet. The [installed source review](integration-widget-version-review.md)
confirms the relevant features at the supplied image-label revisions. Nothing here changes Tower's dashboards, containers,
networking, NFS, media mounts or production storage authority.

## Prerequisites

Deploying an image that actually contains the [API](integration-api.md) and
configuring its dedicated token are separate work. A passing isolated checkout
smoke does not install the API into the running auditor. The security workflow
builds/scans without publishing; do not assume the feature image was updated.
No container update is recommended by these examples.

Choose the auditor URL as seen from the dashboard's server/container, not from
the browser. `localhost` inside a dashboard container refers to that container.
Use a reachable private route or HTTPS reverse proxy. Keep authentication in a
server-side secret/header; no browser JavaScript fetch, token query string,
iframe credential or Docker socket is needed for these widgets.

Use a private board appropriate for the operational counts you expose. A bearer
secret can stay server-side while the resulting data is visible to board viewers.

## Homepage

Merge `examples/integrations/homepage-services.example.yaml` into an existing
`services.yaml`; do not replace unrelated entries. Change both example URLs.
Privately set `HOMEPAGE_VAR_AUDITOR_TOKEN` to the dedicated integration token in
Homepage's deployment configuration. The quoted placeholder is Homepage syntax,
not shell expansion; do not substitute a real secret into the committed example.

The example uses the Custom API service widget, GET, a 60-second refresh and
list display. Counts use text formatting and null-to-Unavailable mappings to
preserve the difference between zero records and missing values. The label
explicitly states that freshness is unverified. A title may have tracking
records in multiple sections, so these values are not a unique-title total.

The upstream component routes request errors to its widget error display; do not
rewrite API 401/404/503 responses into successful empty objects in a proxy. Check
this behavior on the installed version. Cached values retained by a dashboard
are not current evidence even if the API sends no-store headers.

Sources: [Custom API configuration](https://gethomepage.dev/widgets/services/customapi/),
[environment placeholders](https://gethomepage.dev/installation/docker/#using-environment-secrets),
[upstream error rendering](https://github.com/gethomepage/homepage/blob/main/src/widgets/customapi/component.jsx),
[null/text mapping behavior](https://github.com/gethomepage/homepage/blob/main/src/widgets/customapi/utils.js).

## Homarr with Custom Widgets v2

Use these only if the installed Homarr has the documented Custom Widgets v2
workbench. `examples/integrations/homarr-widget.example.json` is the complete
import candidate; the requests/JSX files remain separate editor alternatives.
The candidate still needs Homarr's own schema validation and preview acceptance.
If the feature is absent, keep this integration pending rather than installing
an unreviewed upgrade or exposing credentials through an iframe.

1. Import the complete candidate (or create a definition) under Management →
   Custom Widgets. Configure an HTTP
   source named `default` with the auditor's base URL (without `/api/v1`). Select
   the network scope matching its address and bearer authentication. Enter the
   dedicated token in the source credential field, not in the definition/JSX.
2. Add the named GET queries from `examples/integrations/homarr-requests.example.json`
   in the Requests editor. These use the documented default load-query behavior.
   Declare no actions and no audit/rescue/configuration requests.
3. The import already includes the JSX. For manual authoring, paste
   `examples/integrations/homarr-template.example.jsx` in the JSX editor.
   It renders loading/errors before values and uses null-aware fallbacks. It
   shows coordinator flags separately from tracking records; neither verifies
   live media inventory or collector freshness.
4. Use the workbench's Test/preview controls and schema validation before saving.
   Configure a 60-second board refresh. The supplied queries request zero
   server-cache duration. Review any other dashboard-side response cache
   settings; stale retained data must not be presented as verified current data.

Source setup, bearer credentials, query paths and preview workflow follow
[Homarr requests/security](https://homarr.dev/docs/management/custom-widgets/requests-and-security/)
and [authoring](https://homarr.dev/docs/management/custom-widgets/authoring/).
The template uses the documented `data` and `status` bindings and conditional
rendering from the [safe JSX runtime](https://homarr.dev/docs/management/custom-widgets/custom-jsx/).
Do not assume the current online schema matches an older installed Homarr.

## Acceptance before claiming widget compatibility

Use a disposable API instance and the actual installed widget version. Verify:

| Fixture response | Expected display |
| --- | --- |
| Valid empty tracking object | Zero records, freshness still unverified |
| Known synthetic counts | Exact corresponding record values |
| Missing/invalid state (503) | Unavailable/error, never healthy zero counts |
| Wrong token (401) or disabled API (404) | Authentication/unavailable error |
| Request fails after a prior success | Error/refresh state; old values not treated as current |
| Missing last-run timestamps/result | Unknown, not a successful recent audit |

These renderer checks remain pending. Local API tests already verify the HTTP
status and null/count contract, but do not prove either vendor's rendering,
credential handling, cache behavior or installed-version compatibility.


The separate [HTTP transport fixture](integration-api.md#disposable-http-transport-check)
can verify endpoint wire behavior first without any dashboard change. Its output
explicitly leaves widget rendering unverified; it does not substitute for the
installed-version acceptance table above.

## Read-only installed image metadata

Before choosing an actual renderer test, capture only dashboard names, image
references and selected OCI version/revision metadata. This executes no command
inside a dashboard and reads no environment, credentials, mounts or config files.
Image labels may be absent; a floating image tag alone does not establish the
installed software version. The matching below uses container names/image refs
containing Homepage or Homarr; a fully renamed/re-tagged deployment may need a
separately supplied container name. No matching output is not proof of absence.

Run on the Unraid host:

```sh
(
  set -eu
  docker ps -a --format '{{.Names}}\t{{.Image}}' |
  while IFS=$'\t' read -r dashboard_name dashboard_ref; do
    case "${dashboard_name,,} ${dashboard_ref,,}" in
      *homepage*|*homarr*) ;;
      *) continue ;;
    esac
    printf '\nDashboard: %s\nImage reference: %s\n' "$dashboard_name" "$dashboard_ref"
    dashboard_image_id=$(docker inspect --type container --format '{{.Image}}' "$dashboard_name")
    docker image inspect "$dashboard_image_id" --format \
      'image_id={{.Id}} version={{index .Config.Labels "org.opencontainers.image.version"}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}'
  done
)
```

This is a metadata observation, not an API/widget test or a dashboard update.
Do not add full inspect output or secret-bearing configuration to the report.


## Reachable synthetic API instance

The user confirmed both dashboards use Docker's default `bridge`. The
[expiring widget API lab](integration-widget-lab.md) starts a separate synthetic
instance on that bridge, with no published port or production mounts. It does
not update the auditor image or alter dashboard configuration. Actual widget
import/preview remains a manual step after the new instance is ready.

## Separate title-list widgets (development revision)

Two independent Homarr definitions are provided:

- `examples/integrations/homarr-oldest-waiting-widget.example.json`
- `examples/integrations/homarr-leaving-soon-widget.example.json`

Each has matching `-requests.example.json` and `-template.example.jsx` fragments
for manual entry if whole-definition import is unavailable. Set the `default`
source's URL and bearer credential privately as for the aggregate widget. Both
use the request ID `titles`; create separate definitions, rather than merging
the two request objects under the same ID. No production dashboard changes are
performed by these examples.

The production API requires `INTEGRATION_API_TITLE_DETAILS=true` and a newer
reviewed image containing the title routes. The deployed aggregate-only image
will return 404 for these paths. Do not point these definitions at it yet or
replace it merely to preview the UI. A private board with this credential can
see title names; keep that exposure deliberate.

Rows use the existing Stack/Text primitives with rounded borders and escaped
text interpolation. Ten fixed slots avoid relying on new renderer iteration
features. Dates are local wall time; Holding estimates are not deletion dates.
There is no nested scroll container, image request, browser fetch or navigation
link. Size each board widget to fit its rows; actual no-scroll acceptance depends
on the installed renderer, board height and viewport, especially on mobile.

For a synthetic ten-row preview, update only the checkout on `feature/sqlite`
and run `bash scripts/integration_widget_lab.sh titles`. This uses the existing
expiring isolated fixture launcher, not production state. It exposes both title
routes with twelve synthetic records each, capped at ten with a truncation note.
Use the printed temporary base URL and private token file in the new widget
sources. Its API routes reuse the production projection and do not require a
production title-detail setting. Existing sample/empty/unavailable scenarios
also serve the title routes.

Acceptance needed in Homarr: import or manual JSX validation, all ten rows and
truncation message, correct date order, independent widget sizing without scroll,
empty message, unavailable message and no stale rows after a failed refresh.
Local JSON checks and API fixture tests do not establish renderer acceptance.
The fixture expires after fifteen minutes; never use its URL/token as a permanent
source. No new image build, NFS operation or production container restart is
needed for this preview.

### Poster cards and clickable navigation

The title JSX now adds 44×66 poster thumbnails and safe Anchor components for
matched titles. Posters and an accessible text link open Jellyfin in a new tab.
Titles without artwork show “No poster”; unavailable or ambiguous matches remain
unlinked. Existing title/estimate and loading/error guards are retained. The
initial title-only image remains compatible with this JSX via missing-field
fallbacks. Shipping artwork metadata requires the new API revision and its
explicit opt-in; replacing the template alone does not enable network lookup.

Preview without a production restart using
`bash scripts/integration_widget_lab.sh artwork`. Use the newly printed fixture
URL/token and the updated JSX fragments. The fixture's inert PNG and text-only
navigation destination are intentionally public and synthetic; the title JSON
still requires its private bearer token. Row 3 is ambiguous and unlinked, row 4
has no poster but retains a link, and row 5 is unmatched and unlinked. Other rows
show generated gradient placeholders, not real Jellyfin artwork. Click a poster
and confirm the synthetic destination opens, then check the fallback rows. All
fixture endpoints expire with the isolated container after fifteen minutes.

### Compact title card presentation

The current title templates omit the explanatory paragraphs above the lists and
the separate “Open in Jellyfin” text links. A matched poster remains a labeled,
keyboard-accessible Anchor. A missing poster shows a text fallback without a
navigation link. Loading, unavailable, empty and truncation indicators remain.
The API's freshness and authorization metadata and all lifecycle safeguards are
unchanged; Holding dates retain their estimated-transition label.

Dates display as `MM/DD/YYYY HH:mm` in 24-hour time, for example
`12/10/2026 11:30`. Formatting rearranges the API's validated ISO local wall-time
characters; it performs no timezone conversion, date parsing or browser-local
reinterpretation. Seconds/fractions are hidden, and absent timestamps display
“Unknown”. Both full import definitions contain the same JSX as the separate
editor fragments. Updating a widget template requires no container update.


## Separate TV leaving-soon widget

The combined leaving-soon endpoint includes both Movies and TV tracking records.
Use `/api/v1/titles/leaving-soon?library=TV` for a separate TV list, or
`?library=Movies` for a movie-only list. Filtering occurs before the ten-record
limit, so movie entries cannot hide the first TV item. Invalid or repeated library
filters return HTTP 400. Authentication and title-detail opt-in still apply.

TV examples are `examples/integrations/homarr-tv-leaving-soon-requests.example.json`,
`homarr-tv-leaving-soon-template.example.jsx`, and
`homarr-tv-leaving-soon-widget.example.json`. Use the same Auditor base URL and
private integration token as the existing widgets. The TV template requires
`library_filter=TV`, preserves clickable posters, and shows advisory Holding to
Removal dates. It does not enable TV lifecycle operations or season pruning.
No TV holding records means no tracked TV items for this view; the widget does
not fabricate missing dates or infer tracking merely from folders.

A newly initialized empty SQLite preview has no title records even when the
folder-based dashboard shows media. Preview scans do not persist discovery clocks.
An explicitly reviewed initialization/import is needed to populate tracking.
The operator chose to restore the retained prior tracking records and dates,
including any TV records, into a new private preview root. This preserves old
clocks; it is not a new-clock scan or automatic adoption of live folder changes.


### Homarr query configuration

In Homarr custom requests, put `/api/v1/titles/leaving-soon` in `path` and
`{"library":"TV"}` in the separate `query` object. Do not paste the full API URL
with `?library=TV` into Homarr's Path field. The matching Homarr revision
`9a38404f738f1e50e382095716cc08f3b3751182` exposes `request.query` through its
Query/body/behavior editor. The earlier TV example put the query in the path;
this was corrected after the deployed route worked but Homarr returned the
dashboard-style sign-in response. API URLs used directly by HTTP clients still
correctly use `?library=TV`; only the Homarr manifest representation differs.

## Optional compact Homarr title rows

The existing accepted templates are retained. Three optional layouts use smaller
36×54 posters, one-line titles, a colored Waiting/Holding pill, library labels and
minute-precision dates. Only a matched poster links to Jellyfin. Missing artwork
shows a fixed-size FILM/TV fallback; it does not add a separate text link. No
internal scroll area or fixed list height is imposed; size the Homarr widget to
fit its ten rows. Long titles are truncated visually and retained in the title
attribute and poster accessibility label.

The new prefixes under `examples/integrations/` are:

- `homarr-oldest-waiting-compact` — oldest Waiting tracking records, both libraries.
- `homarr-movies-leaving-soon-compact` — Movies Holding records only.
- `homarr-tv-leaving-soon-compact` — TV Holding records only.

Each has `-template.example.jsx`, `-requests.example.json` and
`-widget.example.json` files. Library filters stay in the request's `query`
object, not the path. Loading or failed requests hide any cached title rows;
empty responses remain distinct from unavailable data. Holding dates retain the
**Est. removal stage** label and are not deletion promises. Dates preserve API
wall-time characters without browser timezone conversion. These presentation
changes do not alter the API, tracking, lifecycle policy or existing widgets.

The layouts use the same Stack, Group, Text, Image and Anchor components as the
accepted examples. The pill is styled Text, avoiding a new component dependency.
The property handling was reviewed against Homarr revision
`9a38404f738f1e50e382095716cc08f3b3751182`:
[runtime components](https://github.com/homarr-labs/homarr/blob/9a38404f738f1e50e382095716cc08f3b3751182/packages/custom-widgets/src/jsx/runtime-components.tsx),
[property sanitizer](https://github.com/homarr-labs/homarr/blob/9a38404f738f1e50e382095716cc08f3b3751182/packages/custom-widgets/src/jsx/safe-properties.ts).
No callbacks, array iteration or data/image URLs are added to the JSX.

Generate and check the synchronized examples with:

```bash
python -B scripts/build_homarr_compact_examples.py
python -B scripts/build_homarr_compact_examples.py --check
npm ci --prefix tests/homarr-render --ignore-scripts --no-audit --no-fund
npm test --prefix tests/homarr-render
```

The pinned development-only esbuild compiler checks JSX syntax and synthetic
render trees for all three templates: ten-row cap, poster-only links, missing
artwork, dates, stale data on errors/loading, wrong schema/library filter and empty
results. It does not prove Homarr component layout or actual browser image access.
The compiler and Node are not part of the production image.

For visual acceptance, start a separate expiring fixture on Tower:

```bash
bash scripts/integration_widget_lab.sh compact
```

This scenario adds synthetic movie and TV Holding records, twelve per library,
plus twelve Waiting records. Filtering happens before the ten-row limit. It uses
only inert fixture artwork and a synthetic navigation destination, with its own
private token. Configure a temporary Homarr widget using the returned fixture
URL and token; do not replace existing board widgets during the first preview.
Check the layout, long titles, fallback rows, poster click and card height. The
fixture expires after fifteen minutes, and production containers/configuration
are not changed. A widget-template update itself requires no auditor image update.
