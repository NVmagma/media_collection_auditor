# Advanced-state JSON rollback rehearsal

This workflow is restricted to an existing marked disposable lab, with
`state.db` and `.sqlite_disposable_rehearsal`. It cannot restore JSON, change
backend authority, activate SQLite, clear intents, or perform media actions.
It closes an offline rehearsal gap: an original JSON backup is intentionally
stale after SQLite tracking has advanced and must never replace newer history.

From the checkout, with `PYTHONPATH=.`:

```sh
python -B scripts/sqlite_disposable_rollback.py export \
  --root /absolute/disposable/lab \
  --candidate-name rollback-candidate-review.json
python -B scripts/sqlite_disposable_rollback.py inspect \
  --root /absolute/disposable/lab \
  --candidate-name rollback-candidate-review.json
```

Export reads one verified SQLite revision under the cooperating-runner lock and
writes a new private, exclusively created JSON candidate. It preserves all
lifecycle clocks, queued Arr requests and unknown fields; fsyncs the file and
parent; parses and compares the result; then verifies the database revision
again. Original JSON/backup and SQLite bytes remain unchanged. The candidate is
plain tracking JSON, not a report, and contains private title/path data. Keep it
inside the disposable lab. Fixed aggregate command reports expose none of it.

Unresolved operations of any kind block export and inspection, even if their
payload is empty. Symlink or hardlinked candidates, invalid/duplicate JSON keys,
unsafe names, concurrent revision changes and durability failures fail closed.
Existing outputs are never overwritten. Partial or uncertain output remains
for investigation and must not be treated as verified merely because it exists.
Inspection compares the candidate against the current revision, so an export
that was previously matching becomes blocked when tracking advances.

A matching report exits 0 but is advisory and non-authorizing. A mismatched or
failed operation exits 2. There is no restore or production cutover switch.
The lab mount must be writable for export and the cooperating-runner lock;
inspection does not write tracking data. External writer exclusion and actual
production restore/restart remain separate requirements. No earlier backup is
automatically restored, and no newer state is discarded.

Local tests advance SQLite history, preserve queued work and unknown Unicode
fields, export fresh JSON, re-import it into a separate offline SQLite database,
and verify complete snapshot parity. This verifies the data conversion, not
production JSON-loader compatibility, an approved release rollback, or host
filesystem durability. A consolidated Unraid rehearsal remains required before
claiming server evidence for this workflow.
