# Read-only tracked-title coverage reconciliation

This increment extends `preview_with_collected_jellyfin`; it does not activate
SQLite in production. The previously passed live Jellyfin full scan on Unraid
remains the baseline. A successful response-contract scan alone does not prove
that every title tracked in SQLite has a matching Jellyfin observation.

The bridge now reports a `coverage` object alongside the existing preview:

- `tracked_titles`: distinct lifecycle keys in Waiting, Holding, Removal, or Keep.
- `covered_titles` and `blocked_titles`: counts for those tracked keys only.
- `titles`: sorted per-key coverage status and blocker codes.
- `untracked_request_count`: collection requests that have no lifecycle key.
- `complete`: every tracked key received a complete, unambiguous observation.

Coverage is derived from the same snapshot used by the decision preview. Duplicate
stage clocks count as one tracked title but still block lifecycle decisions.
Arr retry entries alone are not lifecycle titles. Missing requests are reported
as `jellyfin_title_request_missing`; missing or ambiguous matches retain their
collector blocker codes. No missing observation becomes an all-false signal set.

A title must match for every enumerated Jellyfin user. A response with zero
matching items for one user leaves protection coverage unknown, even if other
users returned a match. This intentionally blocks installations with restricted
user library visibility until an explicit coverage policy is designed.

The collector returns an internal `(item ID, path)` identity only for complete
observations. If separate requests reuse either ID or path, every affected key
is blocked with `jellyfin_identity_shared_by_state_keys`. Raw identities are not
included in the bridge report. Single backslashes in Jellyfin paths are rejected,
consistent with the full-scan validator.

Valid signals retain the existing tag/favorite rules, including `keep-forever`
and `keep-all-seasons`; protection takes precedence over `not-at-all`. No
lifecycle decision function or deletion safeguard is changed. Even complete
coverage cannot clear unresolved operations or authorize deletion. An unresolved
operation also blocks the top-level report for an empty collection.

This remains a caller-mapped, folder-based experimental collector. Requests must
come from a trusted library/state mapping. It does not independently verify that
mapping, prove freshness, reconcile path aliases between hosts, or reuse the
count-only full-scan output as observations. It currently scans for each request;
this is not a production-scale scan optimization. All results are advisory,
`read_only: true`, `authorization: not_authorized`, and production activation is
disabled. It never writes tracking state, moves media, invokes Arr, refreshes
Jellyfin, or authorizes permanent deletion.

## Unraid Docker regression check

Run from the existing Unraid checkout after updating **only** `feature/sqlite`
with a clean fast-forward. Verify `git branch --show-current` first. Do not run a
production container update. This command tests fixture databases and mocked
Jellyfin responses; it is not a new live Jellyfin or production-state scan.

Use the already reviewed Python image digest in `SQLITE_LAB_IMAGE`, as in the
SQLite lab instructions. `--pull=never` avoids pulling an image or building one.
The checkout is mounted read-only. No media or appdata directory is mounted.
Dependency downloads and all test writes go into ephemeral `/tmp`; network is
needed for pip downloads only. No Jellyfin credentials are passed.

```sh
cd /mnt/user/sqlite_lab_checkout
[ "$(git branch --show-current)" = "feature/sqlite" ] || exit 1
docker run --rm --pull=never --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m \
  --mount type=bind,src="$PWD",dst=/workspace,readonly \
  -w /workspace \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/workspace \
  --entrypoint sh \
  "${SQLITE_LAB_IMAGE:?Set the reviewed Python 3.12 image digest used by the lab}" \
  -c 'python -m venv /tmp/testenv &&
      /tmp/testenv/bin/python -m pip install --no-cache-dir pytest==9.1.1 -r requirements.txt &&
      /tmp/testenv/bin/python -m pytest -p no:cacheprovider --basetemp=/tmp/coverage-tests \
        tests/test_sqlite_jellyfin*.py tests/test_sqlite_collection_decision_preview.py -q'
```

For the complete Linux SQLite regression suite in this same disposable container,
replace the final test paths with `tests/test_sqlite*.py`. Some of those existing
tests intentionally move disposable fixture directories under `/tmp`; they have
no production media mounts.

## Validation for this increment

Development host: macOS, Python 3.14, isolated temporary virtual environment.
All 102 focused Jellyfin/collection tests pass; each new coverage test checks that
the SQLite database bytes are unchanged. Python compilation and diff whitespace
checks pass. The broader SQLite run produced 976 passed, 4 skipped, and 18 failed;
all 18 failures encountered the existing Linux-only atomic no-replace rename
guard. The guard was preserved. These are local results, not Unraid validation.

New Unraid/Linux results are pending. GitHub Actions and Docker builds were not
dispatched. Existing workflow triggers were reviewed: the safety and Docker
workflows do not run on pushes of these paths to `feature/sqlite`, and the
security push workflow is limited to dependency, Dockerfile, and workflow paths.
Do not interpret absent Actions runs as a successful Actions check.

## Confirmed Unraid fixture results and live probe

The user subsequently reported **102 focused tests passed** and **998 full
SQLite tests passed** on Unraid with Python 3.12. Both runs reported a Requests
character-detection dependency warning; neither had test failures. These results
validate the reconciliation increment through `8de620d`, not the later live
probe. They supersede the pending fixture-validation status above. They do not
establish live tracked-title coverage.

`scripts/sqlite_jellyfin_tracked_coverage.py --database /lab/state.db` is a new
GET-only live probe. Mount an existing disposable lab database directory at
`/lab` read-only; do not mount production appdata or media. Set
`JELLYFIN_HOST_URL` and `JELLYFIN_API_TOKEN` in the calling shell and pass them by
environment name to Docker. Do not put the token in command arguments or share it
in output. The transport rejects redirects and disables environment proxies.
The database must already exist; this command never migrates or initializes it.

The probe uses the standard state-key convention: bare movie folder keys and
`TV/` followed by a single series folder. Other formats remain uncovered. It
caches users and item pages only within one invocation, including transport
failures, so title count does not multiply live HTTP requests. There is a hard
10,000 unique request budget. Matching still runs through the tested collector
and bridge. Revision changes between request mapping and preview invalidate all
coverage. The output contains only aggregate counts and fixed blocker labels.

This is a coverage check, not a lifecycle action preview: threshold-zero internal
decisions are discarded. A zero exit code means tracked coverage is complete;
it does not authorize operations. Removal or pending intents can still make
`status` blocked with complete coverage. Zero tracked titles means no titles were
validated. Freshness remains independently unverified, and cached pages are not
a transactional Jellyfin snapshot. The probe does not alter tracking state,
clear intents, invoke Arr, refresh Jellyfin, or activate production.

Full read-only Docker command (set `SQLITE_COVERAGE_LAB_DIR` to the dedicated lab
directory containing the existing `state.db`; keep its SQLite WAL/SHM companions
alongside it if present):

```sh
cd /mnt/user/sqlite_lab_checkout
[ "$(git branch --show-current)" = "feature/sqlite" ] || exit 1
git pull --ff-only origin feature/sqlite
docker run --rm --pull=never --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m \
  --mount type=bind,src="$PWD",dst=/workspace,readonly \
  --mount type=bind,src="${SQLITE_COVERAGE_LAB_DIR:?Set your disposable SQLite lab directory}",dst=/lab,readonly \
  -w /workspace \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/workspace \
  -e JELLYFIN_HOST_URL -e JELLYFIN_API_TOKEN \
  --entrypoint sh \
  "${SQLITE_LAB_IMAGE:?Set your reviewed Python lab image digest}" \
  -c 'python -m venv /tmp/testenv &&
      /tmp/testenv/bin/python -m pip install --no-cache-dir -r requirements.txt &&
      /tmp/testenv/bin/python scripts/sqlite_jellyfin_tracked_coverage.py --database /lab/state.db'
```

The live probe is locally fixture-tested; its new code still requires Unraid
validation. No Docker build or GitHub Actions dispatch is required.

### First live probe: blocked before user enumeration

The first Unraid live run against the verified lab copy reported 539 tracked
keys, zero covered keys, 539 blocked keys, and one request. This establishes a
failure before successful `/Users` collection; it does not establish that the
539 titles are absent from Jellyfin. The original probe hid the transport cause.

The diagnostic update adds `transport_failure_counts`, `http_status_counts`, and
`failure_stages`. They count unique attempted request failures, not cached
replays per title. Fixed categories distinguish HTTP errors, rejected redirects,
timeouts, connection/TLS errors, request errors, invalid JSON, and otherwise
unclassified transport errors. HTTP codes are numeric only. No response bodies,
exception messages, URLs, tokens, users, or media identities are printed.
For example, `http_status_counts: {"401": 1}` at `failure_stages: ["users"]`
identifies a rejected users request without exposing authentication details.
An HTTP 200 JSON response with an invalid users shape still fails closed in the
collector; an empty transport-failure report does not mean a valid response.

The update leaves caching, protection validation, read-only mounts and production
activation unchanged. All 119 focused tests pass locally; Unraid rerun pending.
