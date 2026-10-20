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
