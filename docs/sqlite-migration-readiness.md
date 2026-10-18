# SQLite migration readiness (planning only)

Status: **read-only assessment**. The JSON state file remains authoritative. Do not
switch production storage, modify `main`, or create the SQLite integration branch
until the current `feature/unraid` release is validated and the user approves.

## Current state contract

- The auditor reads and writes `STATE_FILE` (default:
  `/app/logs/auditor_state.json`) in `app/collection_auditor.py`.
- The persisted dictionaries are `first_seen` (Waiting), `queued` (Holding),
  `in_removal` (Removal), `keep_seen` (Keep), and `arr_sync_pending`
  (pending Radarr/Sonarr synchronization metadata).
- Lifecycle timestamps are naive local ISO-8601 strings. A migration must retain
  their exact values and interpret them consistently; do not replace historical
  dates with migration time.
- Existing JSON load validation rejects malformed data, invalid timestamps,
  timezone-aware/future timestamps, and invalid pending-sync records. A missing
  file is treated as new installation only when there is no abandoned state-write
  temporary file. The migration must fail closed on unreadable or ambiguous data.
- State saves use a temporary file, flush and fsync, atomic replace, and POSIX
  directory sync. The future database must provide equivalent crash safety.
- `app/web.py` independently loads JSON for dashboard display and currently
  returns an empty dictionary on missing or unreadable JSON. SQLite integration
  should distinguish **unavailable state** from **genuinely empty state** in the
  dashboard, without making the dashboard capable of authorizing deletions.
- Unraid persists `/app/logs` to host appdata; the database, backups, and any
  SQLite journal/WAL files must all live on durable, writable storage.

## Migration safety acceptance criteria

1. Back up the original JSON before any conversion; retain it unchanged and
   recoverable. Never remove it automatically as part of migration.
2. Validate all JSON sections and records before committing any database rows.
   If validation or persistence fails, do not activate the database or run an audit.
3. Migrate timestamps and pending synchronization records losslessly, including
   media-library key prefixes; preserve unknown historical fields unless an
   explicit compatibility policy is approved.
4. Make conversion transactional and idempotent. Interrupted conversion must
   either resume safely or refuse to proceed, never reset lifecycle clocks.
5. Define how to prevent two auditor instances or an auditor and migration from
   concurrently writing state. Dashboard readers must observe consistent data.
6. Block destructive decisions when database state or Jellyfin protection data
   cannot be read. Do not enable permanent filesystem deletion.
7. Test with disposable media and copies of JSON state: empty state, populated
   state, malformed JSON, bad timestamps, interrupted migration, duplicate keys,
   read-only/disk-full storage, concurrent access, and restart persistence.
8. Verify Python safety checks **and** Docker Image GitHub Actions before
   recommending any Unraid image update or a merge.

## Proposed sequence after branch approval

1. Freeze and validate the JSON release on `feature/unraid`; merge to `main`
   only with explicit approval.
2. Create `feature/sqlite` from the approved `main` baseline.
3. Add a storage interface and read-only SQLite prototype with no migration
   side effects or deletion behavior changes.
4. Implement a backup-first, validated, transactional migration and rollback
   tests; then integrate dashboard reads and auditor writes incrementally.
5. Perform full safety verification and controlled testing on disposable media
   before considering a production rollout.
