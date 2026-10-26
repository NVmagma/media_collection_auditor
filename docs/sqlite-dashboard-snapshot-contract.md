# Dashboard tracking snapshot boundary

The live dashboard calls `read_json_dashboard_snapshot` explicitly. Environment
backend flags cannot switch it to SQLite or trigger a fallback. Valid legacy JSON
keeps its original missing-section shape and unknown fields. Core tracking and
Arr retry fields are validated using the shared snapshot invariants; malformed
objects, duplicate JSON keys, invalid timestamps and non-finite JSON values
produce the dashboard's existing visible state-error banner. A missing file
alongside an interrupted JSON write is not treated as a clean installation.

A captured snapshot stores private serialized state and gives each consumer a
detached copy. Inventory and health can use the same captured tracking state
without one consumer mutating another's input. JSON readers capture one file
version; they do not claim the filesystem inventory or Jellyfin is transactional.
The production behavior change is stricter refusal of damaged tracking data.
No state is rewritten, normalized on disk, moved or activated.

`read_experimental_sqlite_dashboard_snapshot` is an explicitly invoked rehearsal
reader. It binds state to one SQLite revision and provides a final stale-session
check. It never opens a missing database as an empty snapshot and never falls
back to JSON after failure. It is not connected to live backend selection.

`compare_dashboard_snapshots` runs a trusted local read-only inventory builder
against detached copies from both sources. It compares full normalized tracking
state, including unknown fields, and the builder results. It rejects SQLite
revision changes and observed JSON changes during the comparison. Any pending
operation keeps the report blocked even if all state/inventory values match.
Reports contain only aggregate parity/revision/authority metadata; no title,
state values, paths or content hashes are included. JSON remains authoritative
and every report denies authorization and SQLite activation.

Regressions use the actual web inventory and collection-health functions with
movie/TV folders and all four lifecycle stages, shared title names, pending Arr
work and unknown state. Additional tests cover consumer mutation, advanced
SQLite divergence, concurrent checkpoints/JSON changes, error-banner display,
legacy JSON shapes and attempts to select SQLite through environment settings.
This establishes fixture parity for the read boundary, not production SQLite
cutover, remote protection freshness or complete gate 9 acceptance.

## Consolidated runner

`scripts/run_sqlite_integration_checks.py --basetemp=/absolute/new/fixtures`
runs the maintained integration set covering migration/rollback, shared locks,
portable copying, Arr readback and dashboard snapshots. Install requirements and
pytest in a disposable environment first. The runner refuses existing fixture
paths and aliases; it never cleans up retained labs. It disables bytecode/cache
writes and supplies an ephemeral test session secret if none was set. It runs
synthetic integration tests, not production services, a Docker build or release
verification. The integration set is targeted, not the complete project suite.
