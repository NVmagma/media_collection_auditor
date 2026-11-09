# Widget compatibility notes

The supplied examples were reviewed against these specific source versions:

| Dashboard | Version/revision reviewed | Surface |
| --- | --- | --- |
| Homepage | v2.6.0, `51cc1684f9f34a7877ed462b8f94c9cc687b4dde` | Custom API list/error rendering and text/null mappings. |
| Homarr | Source revision `9a38404f738f1e50e382095716cc08f3b3751182` | Custom Widgets v2, Bearer HTTP sources, query parameters, cache settings, and JSX bindings. |

These identify the historical review baseline, not the newest versions or a
universal compatibility matrix. Manual Homarr setup and compact movie rendering
were verified during development. Complete JSON definition import, every saved-board
refresh/failure state, and later dashboard releases need their own checks.

The pinned Homepage [component](https://github.com/gethomepage/homepage/blob/51cc1684f9f34a7877ed462b8f94c9cc687b4dde/src/widgets/customapi/component.jsx)
and [mapping helpers](https://github.com/gethomepage/homepage/blob/51cc1684f9f34a7877ed462b8f94c9cc687b4dde/src/widgets/customapi/utils.js)
were used to review errors, nested fields, zero counts, and null remapping.
The pinned Homarr [definition schema](https://github.com/homarr-labs/homarr/blob/9a38404f738f1e50e382095716cc08f3b3751182/packages/custom-widgets/src/core/custom-jsx-schema.ts),
[request schema](https://github.com/homarr-labs/homarr/blob/9a38404f738f1e50e382095716cc08f3b3751182/packages/custom-widgets/src/core/request-schema.ts),
and [property sanitizer](https://github.com/homarr-labs/homarr/blob/9a38404f738f1e50e382095716cc08f3b3751182/packages/custom-widgets/src/jsx/safe-properties.ts)
were used to review sources, GET queries, library filters, and browser-safe artwork links.

Project JSX checks compile and exercise synthetic render trees. They do not
instantiate a vendor dashboard. Test the installed workbench and private network
route with the [expiring fixture](integration-widget-lab.md) before relying on the
[examples](integration-widgets.md) on a shared board.
