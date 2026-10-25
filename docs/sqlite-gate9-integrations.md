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
steps). At that repair CI checkpoint Tower acceptance was pending. The subsequent
9-test shfs/native results recorded above accept the repaired boundary, including
filesystem-specific cleanup.


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

Native Tower acceptance of this queue boundary passed. Repeat command:

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

[Final queue CI run 40131467883](https://github.com/NVmagma/media_collection_auditor/actions/runs/40131467883)
passed for implementation `73376bde9108831a6abf277aab508e50454408d0`: 367 scheduled
and backend-gate tests with 27 subtests, 226 Gate 9/API/catalog checks, 23 atomic
regressions, 671 SQLite regressions and 275 isolated safety tests (separate steps).
All 19 catalog unit/transport tests passed locally. Final isolated Linux checks
passed the 6 queue cases plus 27 rename and 11 HTTP cases. An earlier full package
also passed 9 tracking, 8 runtime, 4 configured-slot, 14 daily-slot, 22 routed,
14 inventory, 16 checkpoint and 19 reconciliation cases. No production activation
or real service update was performed. Native Tower acceptance passed at
`68f0142b7699241217641f01ba8d6c21927117bb`, lab
`/mnt/media/sql_test/arr-queue.UiskXt`: 6 queue cases in 2.259s and
11 HTTP cases in 0.233s; final `arr_queue_acceptance_complete`.

The remaining Arr work is one-shot delivery and independently verified outcome
reconciliation under the same stable identity and local destination binding.
Coordinator/history authority and TV-season compatibility also remain open.

## One-shot HTTP delivery and independent readback boundary

`ArrTitleUpdate` adds one single-use transport attempt to the existing marked-lab
intent runner. It is not connected to the production worker. The runner persists
an Arr intent before the first HTTP request. The transport reads the stable ID,
requires the exact prepared source path, preserves the full resource except for
path/monitoring, and sends one PUT with `moveFiles=false`. It then issues two new
GETs requiring the exact ID, destination folder/root and strict monitoring value.
The PUT response body alone cannot establish completion. Radarr's documented
202 and Sonarr's documented 200 are handled separately; see the official
[Radarr API specification](https://github.com/Radarr/Radarr/blob/develop/src/Radarr.Api.V3/openapi.json)
and [Sonarr API specification](https://github.com/Sonarr/Sonarr/blob/develop/src/Sonarr.Api.V3/openapi.json).

All requests share a response deadline and size bound, reject redirects/proxies,
and redact transport errors. The attempt is consumed on failure. An exception or
lost acknowledgement never causes a retry or opportunistic success readback.
Even two matching readbacks retain the queue and intent: exact local binding,
verified normal-path CAS clearance and configured worker integration remain the
next Arr layer. Generic diagnostic recovery clearance is unchanged and refused.

Eleven private HTTP/SQLite fixtures cover both API acknowledgement shapes, full
resource/season preservation, lost acknowledgement after the remote update,
wrong-folder and second-read disagreement, changed source/ID, HTTP rejection,
redirect refusal, injected failure, and actual SIGKILL after readback. Every case
retains its queue/clock/unknown data and proves that a second dispatch cannot
send another request. Nine additional transport unit cases cover invalid JSON,
size/deadline limits, response closure, redaction and service mismatch.

Tower acceptance is pending. This boundary performs no media rename and should
be exercised on both accepted filesystem parents:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  for parent in /mnt/user/sql_test /mnt/media/sql_test; do
    bash scripts/sqlite_arr_delivery_lab.sh "$parent"
  done
)
```

Expected per parent: 11 delivery cases and 11 HTTP regressions, final
`arr_delivery_acceptance_complete`, scope
`one_shot_arr_delivery_retained_pending`. Only new lab files, one new cached-image
container and private loopback fake Arr services are used. No real Arr/Jellyfin,
production media/state/settings, host services or kernel controls are changed.
This acceptance does not close Gate 9 or authorize queue clearance/activation.

Delivery implementation `81e211792b1046abc6ea4659d2e46be0b80cb3ed` passed
[CI run 40132184733](https://github.com/NVmagma/media_collection_auditor/actions/runs/40132184733):
367 scheduled/backend checks with 27 subtests, 248 Gate 9/API checks, 23 atomic
checks, 671 SQLite regressions and 286 isolated safety tests (separate steps).
Local focused checks passed 90 tests. The isolated Linux container passed 11
delivery, 6 configured queue, 27 rename and 11 HTTP cases, including actual
SIGKILL. Tower acceptance remains pending; production activation stays disabled.


### Tower delivery acceptance

Source `be9e0d37e6e837d36aa150e1f82754d61fb07d55` passed both parents:
`/mnt/user/sql_test/arr-delivery.4i7hkQ`: 11 delivery cases in 6.280s and
11 HTTP cases in 0.238s; `/mnt/media/sql_test/arr-delivery.huSUY8`: 11 delivery
cases in 5.406s and 11 HTTP cases in 0.285s. Both ended with
`arr_delivery_acceptance_complete`, retaining pending state as designed.

## Known-outcome completion in disposable labs

`complete_disposable_arr_request` owns a new transport attempt, pinned database,
stage-parent/title descriptors and one cooperating runner lock. It requires an
exact stable-ID queue and unique destination clock/location before intent. Every
HTTP request checks the same local identities and verified SQLite session.
After acknowledged PUT and two exact independent readbacks, it records the applied
phase, rechecks the chain, and clears only its own queue and intent in one CAS.
Clocks, unrelated queue entries and unknown fields are preserved. Existing
intents are never adopted. The old diagnostic inspector and generic recovery
clearance remain blocked. This helper is not wired to the configured worker or
production entry point; production activation remains sealed.

Fourteen private HTTP/SQLite tests cover Holding/Keep/Removal and movie/TV completion, season preservation,
uncertain PUT/readback, title/root/database replacement, concurrent tracking/queue
changes, final SQL failure, lost final commit acknowledgement and old-intent
refusal. On final SQL failure, the applied intent and queue remain. A lost final
commit acknowledgement may leave the atomic completed state; it raises and stops,
and its missing queue prevents resending. No automatic retry is introduced.

Tower acceptance for this next boundary is pending:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  for parent in /mnt/user/sql_test /mnt/media/sql_test; do
    bash scripts/sqlite_arr_completion_lab.sh "$parent"
  done
)
```

Expected per parent: 14 completion tests and 11 HTTP regressions, ending with
`arr_completion_acceptance_complete`, scope `known_outcome_arr_completion`. Only
new fixture files/container and private fake Arr HTTP are used; no real services,
production media/state/settings or kernel controls change. Gate 9 remains open
for configured-worker delivery integration, coordinator/history authority and
remaining TV-season compatibility.

Completion implementation `daa9231fd3fd142b95eb8a63473fca69179c0d4f` passed
[CI run 40132953606](https://github.com/NVmagma/media_collection_auditor/actions/runs/40132953606):
367 scheduled/backend checks with 27 subtests, 264 Gate 9/API checks, 23 atomic
checks, 671 SQLite regressions and 300 isolated safety tests (separate steps).
Local focused checks passed 132 tests. Final isolated Linux checks passed 14
completion, 27 rename and 11 HTTP cases; the preceding combined package also
passed 11 delivery and 6 queue cases. Tower completion acceptance is pending.


### Tower known-outcome completion acceptance

Source `5f7a773a5d75ba795fa668e40a51d17f6194f7aa` passed both parents:
`/mnt/user/sql_test/arr-completion.rAlX9Q`: 14 completion cases in 8.018s and
11 HTTP cases in 0.238s; `/mnt/media/sql_test/arr-completion.pQiUfc`: 14 completion
cases in 8.442s and 11 HTTP cases in 0.281s. Both ended with
`arr_completion_acceptance_complete`. Production was unchanged.

## Configured scheduled Arr worker integration

The sealed candidate worker now composes scan, globally capped moves, atomic
queue creation, one-shot Arr updates, two exact readbacks and per-title queue/
intent clearance while retaining the daily claim, shared JSON lock and bound
SQLite control lock. The batch supplies its exact final snapshot/revision to
the Arr layer; a fresh read cannot silently replace that authority. Original
scan root/title identities are required before and throughout HTTP. All library
roots stay pinned, and the same run deadline covers collection through final
Arr completion rather than resetting per title.

Only the completed capped batch is eligible. Arr delivery occurs after all
planned moves; a move failure prevents all Arr delivery. A first delivery failure
leaves completed move clocks and both queue entries intact, retains its own
intent, stops before the second delivery, and prevents next-day HTTP replay.
Successful per-title completion advances the shared revision by three while
preserving unrelated state. Existing uncertain intents/old queue requests are
never automatically adopted. No permanent deletion or season pruning is added.

The public production release gate remains unconditional. The configured marked
single-layout lab accepts `deliver_arr=True` explicitly; the private candidate
runtime composes the same callback. The historical GET-only catalog/queue fixture
explicitly disables this callback to retain its earlier queue-only contract;
full delivery uses a separate fake-HTTP fixture.

Nine Linux end-to-end cases cover both identical-name movie/TV identities,
correct application path aliases, source JSON preservation, global cap,
post-move title replacement, first/later lost acknowledgement, mismatched readback, failed
scan, changed per-move protection and shared-lock coverage. The focused transport
suite additionally verifies an expired outer deadline cannot start HTTP.

Native Tower acceptance is pending (actual disposable renames are required):

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  bash scripts/sqlite_scheduled_arr_lab.sh /mnt/media/sql_test
)
```

Expected: 9 configured worker cases and 11 HTTP regressions, final
`scheduled_arr_acceptance_complete`, scope `configured_scheduled_arr_worker`.
Only new fixture media/state and one new isolated container are used. All HTTP
is synthetic private loopback; production services, media, JSON state, settings,
exports and kernel controls remain unchanged. Gate 9 remains open pending this
acceptance plus coordinator/history authority and TV-season compatibility.

Scheduled Arr implementation `78bee331db68ddbb5fba44c6c0c9ae379b72ed96` passed
[CI run 40135429999](https://github.com/NVmagma/media_collection_auditor/actions/runs/40135429999):
378 scheduled/backend checks with 27 subtests, 265 Gate 9/API checks, 23 atomic
checks, 671 SQLite regressions and 309 isolated safety tests (separate steps).
The broad local package passed 343 tests with 14 subtests (Linux cases skipped
on macOS). Final isolated Linux checks passed 9 scheduled Arr, 27 rename and
11 HTTP cases. The combined Linux package also passed 14 completion, 6 queue,
8 runtime, 4 configured-slot, 14 daily-slot and 22 routed cases before the final
additional later-delivery case. Native Tower scheduled Arr acceptance is pending.


### Tower configured Arr worker acceptance

Source `3fcb2111e057f42352f858dc4f703ea7b874b9d0` passed native Tower lab
`/mnt/media/sql_test/scheduled-arr.exULg0`: 9 worker cases in 7.961s and 11 HTTP
cases in 0.234s, ending with `scheduled_arr_acceptance_complete`. This accepts
the configured scheduled Arr boundary; production activation remains disabled.

## Whole-show TV compatibility acceptance

Ten additional configured private-HTTP/Linux fixtures exercise multiple season
folders and specials through real whole-title renames. They verify configured
show-level keep/keep-forever tags, favorites combined across two users, disabled
favorite policy, early dislike routing, keep-all-seasons preservation in Keep,
new-episode clock reset before moving, late protection refusal, unexpected Season
records blocking title protection, and enabled pruning rejection before any
claim or HTTP. Episode bytes and season presence are checked after each run.

This preserves the existing JSON scope: tags/favorites belong on the Series
record, not a Season/Episode. A season-shaped response cannot replace a complete
show protection read. Season pruning and permanent deletion remain unsupported
and must stay disabled. This increment tests supported behavior without enabling
any destructive policy or changing production settings.

Native Tower acceptance is pending:

```bash
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = feature/sqlite ]
  git pull --ff-only origin feature/sqlite
  bash scripts/sqlite_tv_compatibility_lab.sh /mnt/media/sql_test
)
```

Expected: 10 TV cases and 11 HTTP regressions, final
`tv_compatibility_acceptance_complete`, scope `configured_whole_show_tv`. Only
new disposable media/state and one new cached-image container are used, with
synthetic private-loopback Jellyfin responses. No production changes occur.
Coordinator/history authority remains open: the candidate scheduler must not
present legacy JSON history as its own SQLite attempt history or live freshness.
