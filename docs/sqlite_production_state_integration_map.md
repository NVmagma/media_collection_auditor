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


## Production integration readiness review (October 2026)

**Decision: NOT READY for SQLite activation.** Cross-process experiments
demonstrate durable intent persistence and conservative recovery review, but
do not provide a trusted, atomic bridge between media side effects and
checkpoint clearance.

### Proposed per-move execution order

1. Hold the existing single-writer audit lock. Validate state, all relevant
   media paths and fresh Jellyfin protections before preparing any operation.
2. Capture pre-move evidence and persist a unique SQLite move intent using
   revision-checked, read-back-verified checkpointing. If that fails, do not
   perform the move.
3. Execute at most one external move. A timeout, crash, ambiguous destination,
   or failed post-move verification must leave the intent unresolved and stop
   further side effects for that media.
4. Independently observe source and destination, reject duplicates and unsafe
   paths, and verify that the observed media identity corresponds to the
   recorded intent. Existing inode/device fingerprints and unique location
   observations are advisory, **not** sufficient identity proof.
5. Only after trusted verification exists, persist the new stage clock and
   clear the matching intent in one revision-checked transaction. A restart
   must never infer completion merely from a destination folder or caller
   success flag.
6. Treat Arr notification as a separate side effect with its own durable
   retry/unknown-outcome handling; do not replay uncertain requests blindly.

**Important:** steps 4 and 5 are *not implemented*. Existing
`SQLiteOperationCoordinator.reconcile()` deliberately refuses clearance.
The experimental planner also refuses checkpoint authorization. Neither
component should be connected to live moves until a reviewed verification
contract and crash-injection tests are in place.

### Production code touchpoints and order of work

| Priority | Production area | Required change before cutover |
| --- | --- | --- |
| 1 | `run_once()` and `_run_once_locked()` | Keep JSON-only backend gate until explicit approval; design isolated SQLite run session and fail-closed startup checks |
| 2 | `move_or_report()`, `move_to_holding()`, `audit_transient()`, `audit_holding()` | Establish intent-before-move and verified checkpoint-after-move; preserve clocks and action caps |
| 3 | `reconcile_moved_titles()`, `reconcile_untracked_keep()` | Never reconcile or reset clocks past an unresolved intent; handle duplicates and unavailable media safely |
| 4 | `sync_arr()`, `retry_pending_arr_sync()` | Persist retry requests and handle ambiguous remote outcomes without duplicate actions |
| 5 | `audit_removal()`, `audit_keep_seasons()` | Preserve Jellyfin fail-closed checks and show/season protection; do not enable deletion |
| 6 | Dashboard, migration, deployment | Read one authoritative snapshot, back up JSON, prove rollback and run disposable Unraid tests |

### Immediate next implementation milestone

Introduce a **read-only production integration preflight** that inspects
configuration, existing tracking data, and unresolved SQLite intents without
changing `run_once()`, moving media, or activating SQLite. Its result must
remain non-authorizing, even if all checks pass. Add tests for invalid backend
selection, absent or mismatched snapshots, pending intents, and no writes.

### Release gate checklist

- [ ] Trusted independent move verification and atomic intent clearance
- [ ] Crash-injection tests at every move/checkpoint boundary
- [ ] Arr unknown-outcome and restart tests
- [ ] Fresh Jellyfin protection checks and season-wide invariants
- [ ] Read-only dashboard parity and persistent-state rollback rehearsal
- [ ] Full local test suite and disposable-media Unraid validation
- [ ] Manually triggered GitHub Actions and Docker image verification
- [ ] Explicit approval for SQLite production activation

No permanent filesystem deletion approval is implied by SQLite activation.
