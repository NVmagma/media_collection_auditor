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
There is deliberately no apply option yet. A separate tested recovery operation
must take the source/control locks, repeat independent validation and preserve
tracking clocks, unknown fields and all daily/hourly claims when acknowledging
only the selected Arr operation. Ordinary scans must not clear it implicitly.
