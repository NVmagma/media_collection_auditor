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
and verify complete snapshot parity. Additional restart regressions copy the
candidate into a separate disposable JSON directory, then run the actual
`collection_auditor.load_state()` and `save_state()` in fresh Python processes.
They verify full snapshot parity before saving, immediately after saving, and
after another process restart. Fixtures cover advanced lifecycle clocks, movie
and TV keys, Radarr/Sonarr queue metadata, Unicode and unknown fields. Network
requests are forbidden and service credentials are not inherited by the child
processes. Original JSON, SQLite bytes and the exported candidate stay unchanged.

This proves compatibility for the tested fixture states and current loader. It
does not exercise an audit run, authorize a production restore, establish writer
exclusion, or prove host filesystem durability. A consolidated Unraid rehearsal
remains required before claiming server evidence for this workflow.

## Cooperating writer barrier

JSON save and offline migration now open their persistent shared lock without
following symlinks and require a regular file with one link. The held inode is
checked against the lock path after acquisition and on successful release.
An audit carries the verifier into nested JSON saves, which check the binding
before writing. Replaced, symlinked, hardlinked or FIFO lock files fail closed;
there is no automatic unlink, repair or fallback to an unlocked write. An exit
binding failure is uncertain and must not trigger automatic replay.

Separate-process regressions hold a migration lock while invoking the actual
JSON save routine and hold an audit lock while invoking actual offline
migration. Both contenders must stop before state/output writes. After release,
the same operations succeed; the persistent lock inode remains in place.
These tests demonstrate cooperation, not exclusion of old versions or arbitrary
external writers. Parent-path substitution and noncooperating writes still
require operational controls; this barrier does not authorize live cutover.

The production-visible change is additional refusal of unsafe lock files.
Normal JSON state format, backend selection and lifecycle behavior are unchanged.
No SQLite activation, restore or permanent deletion is enabled.

## Single synthetic cutover/restart rehearsal

Run `python -B scripts/sqlite_disposable_cutover_rehearsal.py --root /absolute/new-lab`
with the checkout on `PYTHONPATH`. The directory must not exist; aliases and
existing directories are refused. The command creates only its own private
synthetic state fixtures. It accepts no existing JSON, database, media paths or
service credentials.

The rehearsal performs backup-first migration with exact snapshot parity,
advances lifecycle/Arr/unknown-field tracking through two SQLite checkpoints,
rejects the now-stale earlier JSON export, exports the current revision, and
loads/saves/reloads a separate disposable JSON copy in fresh processes using the
actual application functions. Original JSON, original backup, SQLite bytes and
the latest export must remain unchanged by the JSON restart. Network requests
are forbidden in child processes. All failed artifacts remain for investigation.
A sanitized failure exits 2; a successful advisory report exits 0 and still
explicitly denies production restore/activation. Revision 2 is synthetic tracking
history, not evidence that any media was moved or remote request was delivered.

Consolidated server validation should cover this workflow, shared-lock safety
and separate-process contention, offline migration/rollback, current JSON
persistence, and portable-copy regressions on both filesystem access paths.
These tests do not require production media/appdata mounts or image builds.
Gate 10 still needs an accepted operational restore procedure, noncooperating
writer controls, final release verification and explicit activation approval.
