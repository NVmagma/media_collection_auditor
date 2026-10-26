# Offline integration tracking status

This is the offline reader and response format reused by the
[authenticated summary endpoint](integration-api.md). The CLI itself adds no
listener, network collector or action endpoint.
JSON remains authoritative; SQLite environment flags cannot redirect this reader.
Dedicated bearer authentication is documented with the endpoint.

Run from a checkout with project dependencies installed:

```sh
python -B -m scripts.integration_tracking_status --state /path/to/auditor_state.json
```

Schema version 1 returns only fixed fields and counts. `tracking_counts` contains
waiting, holding, keep, removal and arr_sync_pending record counts from one
captured JSON snapshot. These are tracking records, not verified media inventory;
a title may have records in more than one section. They must not be summed into a
unique-title collection total. Missing legacy sections count as zero only when
an existing state file was successfully read and validated.

Missing, unreadable or invalid state returns `status=unavailable`, null counts and
null pending-operation presence, with exit code 2. A valid empty object reports
zero counts with `status=advisory_only` and exit code 0. Presence of the pending
operation key reports true even if its value is malformed: this report neither
validates nor clears an operation. Unknown extensions are never returned.

`freshness_verified=false` always: reading state does not establish a successful
recent audit, live collector availability or current media locations. No timestamp
is invented from file modification time. Title names, paths, credentials and raw
exceptions are excluded. The response grants no move, restart or recovery permit;
production_activation remains disabled and production_authorized remains false.

Use this CLI only with a trusted local state path. Network endpoints must
supply the configured authoritative path themselves and authenticate before
returning detailed status; they must not expose a caller-controlled file reader.

Local validation on October 22, 2026: 24 focused snapshot/summary tests passed;
the maintained integration suite passed 659 tests and 19 subtests on the local
macOS development host. This is not Unraid filesystem or kernel acceptance.
No GitHub Actions workflow, Docker build or production service change was run.
