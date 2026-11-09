# Expiring widget API fixture

The fixture starts a temporary API server with synthetic collection records and
its own Bearer token. It is useful for checking widget rendering independently
of production tracking. It expires after fifteen minutes.

## Host requirements

This helper was written for an Unraid lab with containers named
`media_collection_auditor`, `homepage`, and `homarr`. It requires both dashboard
containers on Docker's default `bridge`, inter-container communication enabled,
and the auditor's current image cached locally. It refuses mismatched networking
rather than changing it. The production API has no requirement to use these
container names or this network.

Run from a committed checkout matching the fixture source you want to test:

```bash
bash scripts/integration_widget_lab.sh compact
```

| Scenario | Synthetic data |
| --- | --- |
| `sample` | Fixed summary counts and idle status. |
| `empty` | Valid empty tracking and unknown prior result. |
| `unavailable` | HTTP 503 and unknown observations. |
| `titles` | Twelve Waiting/Holding records, capped to ten per title response. |
| `artwork` | Inert fixture images/links and unmatched/ambiguous fallback cases. |
| `compact` | Movie and TV Holding lists plus Waiting records for compact layouts. |

The output includes `fixture_url`, `container_id`, `token_file`, and a
900-second lifetime. Use the printed URL from the dashboard server's network
context. Read the temporary token file privately when configuring a temporary
widget source. Change the URL and token together when switching fixtures.

## Scope and cleanup

The fixture uses a read-only checkout/root filesystem, new synthetic state in
container tmpfs, dropped capabilities, and no-new-privileges. It has no production
media/appdata or Docker socket mount, publishes no host port, and starts no scan
worker. Responses identify themselves as fixture data. The bridge IP can be
reachable by other bridge peers, so retain Bearer authentication.

After expiry Docker removes the fixture container. The new host token directory
under `/tmp/auditor-widget.*` remains for explicit cleanup. The token is only for
this temporary server. Stop early using the exact printed container ID if needed.
The helper does not stop existing containers or change dashboard configuration.

Use a new temporary widget definition and verify counts, empty/error states,
artwork/link behavior, row limits, and failed refresh after a success. API startup
alone proves only the fixture's own readiness. Actual dashboard import, saved-board
refresh, and browser access need checks in that dashboard. See
[widget setup](integration-widgets.md) and [compatibility notes](integration-widget-version-review.md).
