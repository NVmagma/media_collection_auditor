# JSON worker operations

The running worker uses `/app/logs/auditor_state.json` as its primary tracking
store. Settings, persistent scan history and the operation journal also live in
appdata. Ordinary valid settings changes do not require release bindings.

## Scans and limits

Daily scans start at `DAILY_RUN_TIME` in `DAILY_RUN_TIMEZONE` (or `TZ`). Manual
live scans require explicit confirmation and share the one-hour cooldown.
Only one scan can run at a time. The initial limits are five actions per library
and ten total per scan; a lower total limit can be configured. The five-per-library
limit remains enforced. Removing limits requires a separate reviewed change.

Waiting titles can move to Holding or Keep. Holding titles can move to Removal
or Keep. `keep-forever` protects the whole title; `keep` and configured favorites
select retention. `not-at-all` selects early Holding. Each move repeats Jellyfin
protection and Arr identity checks. Unknown protection blocks the affected title.
A missing Arr record is skipped without consuming its library's action slot.
Removal deletion is disabled by default and requires explicit warning acknowledgement. Cross-filesystem copy fallback and season pruning remain unavailable.

## Persistent state and recovery

The worker holds one nonblocking writer lock throughout each scan and uses atomic
JSON checkpoints. Unknown tracking fields and saved clocks are preserved. Missing
or corrupt tracking/settings pause scanning; they never select fresh empty state.
A durable journal precedes a rename, Arr update or import. Lost acknowledgements
are not replayed automatically.

Use **Operation recovery** to review an unresolved move or sync using local
filesystem evidence and GET-only remote readbacks. Apply only the displayed,
fingerprint-bound resolution. Already matched Arr state can be acknowledged
without another PUT. A separately reviewed remaining update is available when
appropriate. Recovery never repeats a move merely because its acknowledgement
was lost. Existing-media import recovery is in **Arr imports**.

## Logs and backup

Activity Logs, JSONL downloads and diagnostics read persistent JSON scan history.
Verified completions, proposals, skipped titles and uncertain outcomes remain
separate. The dashboard displays a bounded selection of per-title decisions;
that display limit is not the scan's inventory limit. Unknown counts stay unknown.

Before maintenance, create a new private backup with `app.json_backup.create_backup`
using the current state/settings paths and a new destination directory. It holds
the writer lock, preserves the full tracking document and writes a fingerprinted
receipt. Backups are not automatic restore authority. `/api/v1/backup-status`
verifies only the explicitly selected JSON packet, never current-state freshness
or restore readiness. Retained host backups and containers are not deleted by
source cleanup.

## Container updates

Build `docker/runtime.Dockerfile` and use the accepted immutable published digest.
Edit the existing Unraid template's Repository and Apply while retaining its media
and logs paths, port mapping and security options. The template must point to the
same digest and paths as the running container. Never initialize an existing logs
directory during an update. A retained old container must remain stopped while
its replacement is running.

New installations may run `python -B -m app.json_initialize` explicitly with an
empty writable `/app/logs` directory. This creates empty tracking/settings and
scan-control metadata only. It refuses any nonempty directory, including a partial
initialization. The normal entrypoint never initializes tracking implicitly.

## Optional Removal deletion

Whole-title Removal deletion now has a separate warning and acknowledgement. It is disabled by default and initially limited to one deletion per library per scan. Read [Removal deletion](removal-deletion.md) before opting in. Season pruning and direct filesystem deletion remain unavailable.

## Metadata-only leftovers

Recursive video detection preserves real, hidden, partial and unknown content. [Orphan metadata quarantine](orphan-metadata-quarantine.md) is a separate opt-in: it requires complete service absence checks and 24 hours of stable observations, retains files recoverably, and never enables permanent deletion.
