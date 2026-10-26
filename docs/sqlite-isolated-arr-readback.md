# Isolated Arr outcome readback

`inspect_isolated_arr_outcome(root=..., fetch=...)` connects persisted isolated
Arr delivery intents to two fresh read observations. `inspect_isolated_arr_http`
provides an authenticated GET-only adapter with separately supplied Radarr and
Sonarr endpoints/keys. No Jellyfin credentials are required for this diagnostic.
No production route or caller is connected.

Before any service access, the inspector requires a marked disposable lab,
a pending Arr intent, a matching persistent queue with stable service/title ID,
a single matching lifecycle clock and a unique title directory at the recorded
stage. Historical queue entries without stable service/ID are refused rather
than inferred from a title string. Wrong or ambiguous local bindings stop
before network access.

The adapter requests only `/api/v3/movie/<id>` or `/api/v3/series/<id>`, authenticates
with X-Api-Key and rejects redirects/non-success responses. The default session
disables environment proxies and closes after inspection. URL credentials,
queries/fragments and malformed paths/ports are refused. It exposes no write or
retry operation; no secrets, URL, remote body, title name or path enters reports.
The injected transport, if used, must be trusted.

Two responses must agree on stable ID, exact title folder/path and strict
monitoring boolean. Root/folder/monitoring mismatches and changed responses remain
blocked. Each response is bound to its service/title ID and aware timestamp;
wall-clock and monotonic budgets are checked through the final observation.
The SQLite snapshot and local directory identity are rechecked after fetching.
Concurrent SQLite or local destination changes reject the report, even if a
remote observation appeared valid.

Matching results say `matching_record_unverified`, with retry and clearance
both false. A match cannot establish which request caused the current remote
state, prove crash history or provide transactional Jellyfin protection.
Acknowledged and unknown delivery intents remain pending. The inspector never
replays a request, updates tracking, dequeues Arr work, clears an intent, or
moves/deletes media. Transport failures return a fixed redacted observation;
stale SQLite/local bindings remain errors. Root locks coordinate cooperating
runners only, not remote/external writers.

Tests use synthetic GET responses for Radarr and Sonarr. They are not evidence
of a new live Arr check or authorization for remote mutations. Production
activation and recovery authority remain disabled. Gate 9 stays in progress.

## Operator command

With checkout on `PYTHONPATH`, use
`python -B scripts/sqlite_isolated_arr_readback.py --root /absolute/existing/lab`.
Credentials are read only from explicitly supplied `RADARR_URL`/`RADARR_API_KEY`
and/or `SONARR_URL`/`SONARR_API_KEY` environment values; no `.env` is loaded and
no keys are accepted on the command line. Only the service bound to the pending
intent is queried. The directory must already be a marked disposable lab with
an Arr intent; production appdata is not an accepted substitute. A writable lab
mount is needed for the cooperating lock, while tracking/media remain read-only.

A matching unverified readback exits 0 but grants no clearance. All other results
exit 2. Reports stay blocked, redacted and non-authorizing; no replay/clear flags
exist. This command has not been run against live user Arr services. Existing
synthetic fixtures validate the adapter without requiring live API credentials.
