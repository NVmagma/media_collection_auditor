# Retained Arr intent review

A completed folder move can be followed by an uncertain Arr acknowledgment.
The durable `arr_sync` intent blocks further execution, even if a later remote
catalog shows the requested destination. Do not repeat the move, resend the PUT,
restore an older tracking snapshot, or remove the intent manually.

`scripts/sqlite_arr_recovery_review.py` is a read-only first step. Stream it into
the current container so its packaged read authority validates the live binding:

```bash
docker exec -i media_collection_auditor python -B - < scripts/sqlite_arr_recovery_review.py
```

The script checks the exact intent/queue, a unique destination clock, a unique
local stage folder pinned throughout review, and two fresh authenticated catalog
GETs with matching integer ID, full destination path and monitoring setting.
Local filesystem roots and remote APP path aliases may differ. Concurrent state
changes invalidate the whole result. No request, state, credentials or raw
exception text are printed. HTTP uses the existing bounded no-redirect/no-proxy
Arr GET transport.

A matching report is an observation, not clearance. Its fingerprint identifies
the observed state revision and current destination identity; it does not prove
the original moved inode, original acknowledgment, full media contents, or
exclude uncooperative external writers. The intent and queue remain unchanged.
The separate explicit reconciliation option is:

```bash
docker exec -i media_collection_auditor python -B - \
  --reconcile-reviewed-fingerprint REVIEW_SHA256 < scripts/sqlite_arr_recovery_review.py
```

Use only the fingerprint from a successful current review. This operation
requires the packaged live profile, validates the live binding and safe policy,
takes the source and control locks in worker order, and pins them through a
fresh review and single guarded SQLite compare-and-swap. A stale fingerprint
refuses before any HTTP request. The operation removes only the exact verified
intent and its Arr queue entry. Tracking clocks, other queues, unknown fields
and daily/hourly claim files are preserved. No PUT, media move, service restart,
claim reset or historical scan completion is performed.

An interruption before commit retains the original intent; one after commit
leaves both entries cleared. Repeating the old command after clearance refuses,
and does not resend anything. A reported `blocked_or_uncertain` result may follow
a committed write: inspect current state instead of assuming nothing changed or
retrying automatically. No rollback to an old snapshot is offered. Ordinary
scans still cannot clear an intent implicitly. The scheduler's real authority
check determines when execution can resume; review status alone never does.

## A subsequent scan fails without an intent

Do not repeat reconciliation: a new failure may have a different cause.
`scripts/sqlite_scan_preflight_review.py` runs the existing configured GET-only
collector and Arr catalog resolver under the worker locks, without claiming a
slot, writing discovery clocks, moving media, or sending Arr updates:

```bash
docker exec -i media_collection_auditor python -B - < scripts/sqlite_scan_preflight_review.py
```

Its report identifies the diagnostic stage, bounded code locations on failure,
and full evaluated-title count when preparation returns. Exception text and
private remote payloads are not printed. If discovery clocks need a checkpoint,
the diagnostic reports that condition and stops without simulating a committed
plan. Success covers preparation/catalog reads only, not execution or historical
failure reconstruction. Activity's retained 100-row sample is separate from the
worker's 100,000-title collection ceiling and the live one-per-library move cap.
