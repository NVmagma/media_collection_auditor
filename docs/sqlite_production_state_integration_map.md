# Production state integration map (SQLite planning only)

Branch: `feature/sqlite`. No production backend activation or deletion approval.

## Current JSON lifecycle

- `app/collection_auditor.py:1389-1403`: `_run_once_locked()` loads
  JSON state once, runs each library's reconciliation, Arr retry, Removal,
  Holding, Waiting and optional Keep-season audit, then saves in `finally`.
- `load_state()` (line 212) validates core tracking sections and refuses
  damaged history. `save_state()` (line 264) uses an atomic JSON writer.
- `move_to_holding()` (line 855) updates `queued` and removes
  `first_seen` only after a successful move, then calls Arr sync.
- `audit_holding()` (line 992) and `audit_transient()` (line 1029)
  similarly update stage clocks after successful moves.
- `audit_removal()` (line 942) checks duplicates, unavailable Jellyfin
  signals, and protection before any deletion candidate is considered.
  Permanent filesystem deletion must remain disabled.
- `reconcile_moved_titles()` (line 869) can repair stale stage clocks from
  uniquely observed filesystem locations, including after interrupted moves.
- `sync_arr()` (line 697) records retry requests; `retry_pending_arr_sync()`
  (line 719) checks the recorded destination before retrying.
- `audit_keep_seasons()` (line 1099) uses `keep_seen` timestamps.
- `run_once()` (line 1349) rejects non-JSON backend selections before
  side effects.

## Integration blockers

1. **Move/checkpoint crash gap:** current state is saved at the end of the
   run. SQLite needs a durable intent *before* a move and verified checkpoint
   *after* it, without marking a move complete merely because the SQLite
   transaction committed.
2. **Recovery precedence:** existing location-based reconciliation must not
   override unresolved SQLite intents or silently infer completion. Require
   independent verification and fail closed for missing/ambiguous paths.
3. **Arr side effects:** persist retry state and distinguish notification
   success, timeout, and unknown outcome. Do not replay an uncertain request
   without verification.
4. **Protection:** retain fresh Jellyfin checks for all media, especially
   `keep-forever`, `keep-all-seasons`, favorites, and Removal. Historical
   tags in tracking are not trusted live signals.
5. **TV-season lifecycle:** maintain distinct season clocks and show-level
   protection across the full title.
6. **State contract:** retain all core sections, optional/legacy fields and
   strict timestamp validation; ensure dashboard reads use the same verified
   authoritative snapshot.
7. **Operational cutover:** stopped-auditor migration, durable backups,
   single-writer enforcement, explicit rollback and Unraid container testing.

## Recommended next small implementation

Create a **pure transition checkpoint planner** that describes the intended
tracking changes for a verified move, without executing it or writing either
backend. Test stage-clock changes, no-op/ambiguous outcomes, season identities,
and pending-intent blocking against disposable state.

Do not wire the planner into `run_once()` until trusted recovery and
checkpoint ordering are implemented and reviewed.

## Release gates

Run local disposable-media failure injection and full tests, then manually
verify GitHub Actions and Docker build before recommending deployment.
Keep production JSON authoritative and permanent deletion disabled.
