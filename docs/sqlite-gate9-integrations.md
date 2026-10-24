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

Nine stdlib fixture tests cover one capture for all views, detached dashboard
state, an actual independent-process checkpoint during projection, identical-byte
database replacement, missing SQLite with valid adjacent JSON, pending/secret
redaction, symlink refusal, whole-response projection failure, and same-revision
raw mutation, plus connection closure without relying on garbage collection. Read-only projection creates no missing database or retry action.

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

Expected per view: 9 tests, final `tracking_view_acceptance_complete`, scope
`candidate_tracking_views`. The launcher uses only one new directory and new
cached-image container per invocation, without network, host mounts outside that
new directory, packages, production settings/credentials or service operations.
The repaired reader boundary is accepted on both views at source
`4b6ef271b5a80504f9561ac1e5bf1b4126f93ff7`: shfs lab
`/mnt/user/sql_test/tracking-views.HHO7VM` passed 9 tests in 2.209 seconds;
native lab `/mnt/media/sql_test/tracking-views.79Ae7u` passed 9 tests in
2.513 seconds. Both ended in `tracking_view_acceptance_complete`, scope
`candidate_tracking_views`, with cleanup successful and production unchanged.

Local dashboard/API/runtime regression checks passed 194 tests. The reader
fixture passed all 8 tests both locally and in the cached isolated Linux package;
that package also passed 8 candidate runtime, 27 rename and 11 HTTP regression
cases without host mounts or external network.
[Test-only CI run 40130132387](https://github.com/NVmagma/media_collection_auditor/actions/runs/40130132387)
passed for implementation `9f3fdcd5075d176b4d75cd7f0d1af29ce4cde339`: 367 scheduled
and backend-gate tests with 27 subtests, 194 Gate 9/API/runtime checks, 23 atomic
regressions, 671 SQLite regressions and 268 isolated safety tests (separate steps).
No deployment or production activation was performed. Later documentation-only
commits retain the tested app/scripts/tests/workflow implementation tree.

## Still open after the tracking reader increment

Arr configured queue/delivery/readback reconciliation, coordinator/history authority,
and the remaining TV-season compatibility checks. This increment does not close
Gate 9 or enable SQLite, Arr mutations, pruning or deletion in production.


## First shfs run: cleanup failure and connection-lifetime repair

Source `c5d2106c277b561c268fb95e0fbb0155676230b0`, lab
`/mnt/user/sql_test/tracking-views.GY1bsc`, failed all eight cases during
`TemporaryDirectory` cleanup with `ENOTEMPTY`. No test-assertion failure was
reported, but the lab is **not accepted**. The enclosing `set -eu` command stopped
before the native invocation; native acceptance was not received.

Inspection found SQLite connection-lifetime defects: `_revision()` and offline
snapshot creation used transaction context managers without explicitly closing the
connections. A fixture raw-SQL mutation did the same. On FUSE, retained open files
can prevent directory cleanup after unlink/replacement; the exact remaining file
names were not supplied. The confirmed lifetime defects are repaired with explicit
`contextlib.closing`, preserving transaction commit/rollback and failed-artifact
retention. Cleanup errors are not ignored, and no broad deletion/retry workaround
is added. Existing failed fixture artifacts need not be manually removed to rerun.

Four regression tests keep strong references to all connections so garbage
collection cannot hide leaks. They verify closure after success/failure, revision
and projection reads, file replacement/removal, and failed-output retention. A
ninth stdlib fixture case checks this same lifetime contract on Tower before
cleanup. All nine cases still require successful cleanup. Rerun the two-view
command above after pulling the repair; production remains unchanged.


Repair validation: local storage/worker/API regressions passed 494 tests and 14
subtests (103 Linux-only cases skipped locally). The isolated Linux package passed
9 reader, 8 candidate-runtime, 27 rename and 11 HTTP cases with successful cleanup.
[Test-only CI run 40130538886](https://github.com/NVmagma/media_collection_auditor/actions/runs/40130538886)
passed for repair implementation `b7b37ee9b306320e5fbcca485643dffb507e4d9f`: 367
scheduled/backend-gate tests and 27 subtests, 199 Gate 9/API/lifetime checks, 23
atomic regressions, 671 SQLite regressions and 269 isolated safety tests (separate
steps). The repaired shfs/native acceptance remains pending; CI does not replace
Tower's filesystem-specific cleanup check.


## Configured Arr identities and atomic queue preparation

After the complete Jellyfin/library scan and any required clock checkpoint/rebuild,
the candidate worker resolves **all planned Arr requests before the first move**.
The [Radarr v3 catalog](https://radarr.video/docs/api/) and
[Sonarr v3 catalog](https://sonarr.tv/docs/api/) are requested via bounded,
authenticated GET only (`/api/v3/movie` and `/api/v3/series`). One fresh catalog
per planned service is allowed per attempt, with no retry, redirects, inherited
proxy settings, mutating methods or credentials in persisted requests.

Enabled services require both URL and key; a partial configuration fails before
claim/collection. Both blank retains the existing disabled-service behavior.
Catalog records need unique positive integer IDs, strict monitoring booleans,
canonical paths and unambiguous exact folder names. Movie/TV routing is separate,
even with identical names. The current source path must match the configured Arr
view; Holding/Keep/Removal `*_APP_*_PATH` aliases are distinct from filesystem
roots. Waiting uses the existing transient filesystem path, matching the current
configuration vocabulary. A source-path mismatch blocks rather than guessing.

Destination requests persist only service, stable ID, application root and boolean
monitoring. Holding/Removal requests disable monitoring. Holding-to-Keep enables
it; Waiting-to-Keep preserves the current Arr boolean, matching JSON behavior.
Requests are prepared only for the globally capped plan. Every successful move
commits its matching request with its destination clock and exact intent clearance
in the accepted single CAS; existing unrelated queue entries remain untouched.
A later catalog failure prevents *every* move in that attempt. The retained daily
claim prevents automatic same-date retry. Unknown outcomes and earlier unresolved
queues retain their existing blocking behavior; there is no delivery or clearance
in this increment.

Nineteen pure/transport tests verify identities, aliases, monitoring policy,
configuration detachment, service separation, ambiguity/missing-source refusal,
one-read-per-service, invalid URLs, redacted no-retry failures, explicit HTTP
error-body closure and response deadline enforcement. Six end-to-end
stdlib Linux tests combine synthetic private GET catalogs, actual two-library
media renames, durable claims and SQLite queue/clock reconciliation. They cover
both queued identities, later-service failure, ambiguity, global cap, partial
credentials and wrong source root. The catalog fixture verifies its requests occur
after the complete Jellyfin scan and before either per-move refresh. No real Arr
service is contacted.

Native Tower acceptance of this queue boundary is pending:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  bash scripts/sqlite_arr_queue_lab.sh /mnt/media/sql_test
)
```

Expected: 6 configured queue tests plus 11 HTTP regressions, final
`arr_queue_acceptance_complete`, scope `configured_arr_queue`. Only new marked
fixture files/container and synthetic loopback HTTP are used. Actual fixture
renames require the accepted native parent; no shfs rename fallback is added.
Production Arr/Jellyfin/media/state/settings/services remain unchanged.

The remaining Arr work is one-shot delivery and independently verified outcome
reconciliation under the same stable identity and local destination binding.
Coordinator/history authority and TV-season compatibility also remain open.
