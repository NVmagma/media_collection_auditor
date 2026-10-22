# Dashboard integration examples

These are opt-in configuration examples, not a deployment step or a promise that
the installed dashboards support the latest upstream format. They were checked
against upstream documentation on October 22, 2026; no Homepage/Homarr instance
has rendered them yet. Nothing here changes Tower's dashboards, containers,
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
workbench. They are editor fragments, not a complete importable widget manifest.
If the feature is absent, keep this integration pending rather than installing
an unreviewed upgrade or exposing credentials through an iframe.

1. Create a definition under Management → Custom Widgets. Configure an HTTP
   source named `default` with the auditor's base URL (without `/api/v1`). Select
   the network scope matching its address and bearer authentication. Enter the
   dedicated token in the source credential field, not in the definition/JSX.
2. Add the named GET queries from `examples/integrations/homarr-requests.example.json`
   in the Requests editor. These use the documented default load-query behavior.
   Declare no actions and no audit/rescue/configuration requests.
3. Paste `examples/integrations/homarr-template.example.jsx` in the JSX editor.
   It renders loading/errors before values and uses null-aware fallbacks. It
   shows coordinator flags separately from tracking records; neither verifies
   live media inventory or collector freshness.
4. Use the workbench's Test/preview controls and schema validation before saving.
   Configure a 60-second board refresh. Review any dashboard-side response cache
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
