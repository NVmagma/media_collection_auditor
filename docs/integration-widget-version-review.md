# Installed dashboard source review — October 22, 2026

The user supplied selected image metadata from Tower. No dashboard was updated,
restarted or configured. These are image-label observations and review of the
corresponding public source revisions, not runtime rendering acceptance or a
cryptographic attestation of the installed image contents.

| Dashboard | Reported image version | Labeled source revision | Source capability reviewed |
| --- | --- | --- | --- |
| Homepage | v2.6.0 | `51cc1684f9f34a7877ed462b8f94c9cc687b4dde` | Custom API list rendering, error path, nested field lookup and null remapping |
| Homarr | main (not a semantic release version) | `9a38404f738f1e50e382095716cc08f3b3751182` | Custom Widgets v2, HTTP bearer source, GET load queries, request cache setting and status bindings |

Reported image IDs:

- Homepage: `sha256:6aae731daca383f9a202f98d77fe397323a2507e18c4e0c7e8da6ff5aa17805b`
- Homarr: `sha256:379118eae8cfe67cfdc2d5722b87784c57e9e1cae5a27117bdfb8142529775c0`

The source findings support using the existing dashboard versions for the next
compatibility check. No upgrade is required by this review. Proxy authentication,
network access, actual import/JSX validation and stale-value rendering still need
acceptance in the real applications or suitable disposable copies.

## Homepage evidence

The pinned [Custom API component](https://github.com/gethomepage/homepage/blob/51cc1684f9f34a7877ed462b8f94c9cc687b4dde/src/widgets/customapi/component.jsx)
implements list display and an error branch before rendering values. The pinned
[field/format helpers](https://github.com/gethomepage/homepage/blob/51cc1684f9f34a7877ed462b8f94c9cc687b4dde/src/widgets/customapi/utils.js)
preserve zero values in nested lookup and compare remap values strictly, supporting
the example's text-format null-to-Unavailable mapping. This does not establish
whether every upstream HTTP error reaches that branch on the user's live setup.

## Homarr evidence and import artifact

The pinned [definition schema](https://github.com/homarr-labs/homarr/blob/9a38404f738f1e50e382095716cc08f3b3751182/packages/custom-widgets/src/core/custom-jsx-schema.ts)
accepts a `homarr-custom-widget-v2` definition with sources, requests, options and
a JSX template. Its import path uses that schema, including the runtime's own
JSX and credential-free checks. The pinned
[request schema](https://github.com/homarr-labs/homarr/blob/9a38404f738f1e50e382095716cc08f3b3751182/packages/custom-widgets/src/core/request-schema.ts)
supports an HTTP source with `auth: bearer`, load queries, view permission and
`cacheSeconds: 0`. Its [runtime types](https://github.com/homarr-labs/homarr/blob/9a38404f738f1e50e382095716cc08f3b3751182/packages/custom-widgets/src/runtime/types.ts)
provide the loading/ok flags used by the example template.

`examples/integrations/homarr-widget.example.json` is now a complete import
candidate, combining the existing request/template fragments. It contains:

- A placeholder private HTTP source using separate bearer credentials.
- Exactly two GET load queries, with view permission and request cache set to zero.
- Loading/unavailable branches and explicit unverified-freshness text.
- No action requests, embedded credential, icon fetch or production URL.

Zero request-cache duration is a schema-supported setting, not a claim that all
client/cache layers have been tested. Import validation and preview remain
pending. Local checks parsed the JSON, checked agreement with the editor template,
and inspected the two GET-only requests. Homarr's own validator has not run here;
no new dependency installation or full upstream build was performed.

When an API-containing test instance is ready, import this candidate under
Management → Custom Widgets, configure the source URL/network scope and bearer
credential separately, then run validation/preview before placing it on a board.
Do not import the small requests fragment as a complete widget. The current
running auditor image has not been updated by this work.
