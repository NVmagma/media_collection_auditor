# Gate 9 — external integration acceptance

Gate 8 is closed. Gate 9 remains open; production is JSON and SQLite activation
stays sealed. No production services, database, media, exports or kernel controls
are changed by this work. Permanent deletion remains disabled.

## Fixed remaining scope

1. Connect configured Radarr/Sonarr stable identities and application paths to
   durable per-title queue requests, bounded one-shot delivery and independently
   verified outcomes. Unknown outcomes must retain pending state and never be
   automatically resent. A successful HTTP response alone cannot clear intent.
2. Make dashboard/API tracking reads use the selected state authority and a
   single detached verified SQLite revision. No JSON shadow/fallback after SQLite
   selection, healthy-empty presentation on errors, or secret/pending-detail leaks.
   Coordinator/history projection must accurately distinguish scheduler and
   live-inventory freshness from tracking observations.
3. Verify configured Jellyfin tag/favorite behavior across whole-show/season
   records, including keep-forever/keep-all-seasons and new-content clocks. Season
   pruning must stay disabled until its safety/compatibility boundary is accepted;
   an unsupported enabled policy cannot be silently ignored.

Gate 10 owns release image/runtime packaging, operational migration/backup/rollback
and explicit activation approval. Gate 9 fixtures cannot authorize activation.

## Single-snapshot dashboard/API authority boundary

`capture_candidate_tracking_view` holds a no-follow database descriptor and its
parent identity, captures one validated revision, builds summary and both title
projections from that detached capture, then rechecks the exact snapshot/revision
and database identity before returning. Missing/damaged/linked/replaced state,
concurrent checkpoints, raw same-revision mutation and projection errors reject
the entire capture. No JSON path is supplied to this reader, so fallback is
impossible. Candidate dashboard state uses the same capture boundary and remains
detached for inventory consumers. Pending intent presence is visible but its
payload and unknown extension values never appear in the fixed API projections.

The normal JSON reader/CLI retains its one-capture behavior and schema. The web
summary/title routes now explicitly select through the backend boundary. With
`AUDITOR_STATE_BACKEND=sqlite` while release activation is sealed, they return
503/unavailable with no counts/items rather than misleading JSON data. Dashboard
state loading likewise refuses that unsupported selection instead of returning
JSON. Default JSON mode, API bearer authentication, poster/link projection,
read-only service entry and copied production-image runtime imports remain
unchanged. No new runtime COPY dependency was added: selection logic lives in
an already shipped module. The release gate runs before importing candidate
SQLite modules in the shipped runtime.

The explicit candidate response is labeled `sqlite_candidate`, includes the one
`state_revision` on every child projection, keeps `freshness_verified=false`, and
returns no transition/production authority. Tracking counts are still tracking
records, not live inventory. The selector is not an activation switch.

## Disposable Tower acceptance

Eight stdlib fixture tests cover one capture for all views, detached dashboard
state, an actual independent-process checkpoint during projection, identical-byte
database replacement, missing SQLite with valid adjacent JSON, pending/secret
redaction, symlink refusal, whole-response projection failure, and same-revision
raw mutation. Read-only projection creates no missing database or retry action.

Run on either existing disposable filesystem view; both views are useful for this
SQLite reader boundary (no media rename capability is needed):

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  bash scripts/sqlite_tracking_view_lab.sh /mnt/user/sql_test
  bash scripts/sqlite_tracking_view_lab.sh /mnt/media/sql_test
)
```

Expected per view: 8 tests, final `tracking_view_acceptance_complete`, scope
`candidate_tracking_views`. The launcher uses only one new directory and new
cached-image container per invocation, without network, host mounts outside that
new directory, packages, production settings/credentials or service operations.
Native/shfs acceptance is pending.

Local dashboard/API/runtime regression checks passed 194 tests. The reader
fixture also passed its independent-process SQLite checks locally. Exact-source
CI and isolated Linux validation are recorded below after completion.

## Still open after the tracking reader increment

Arr configured queue/delivery/readback reconciliation, coordinator/history authority,
and the remaining TV-season compatibility checks. This increment does not close
Gate 9 or enable SQLite, Arr mutations, pruning or deletion in production.
