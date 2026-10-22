# Read-only integration API v1

`GET /api/v1/summary` exposes the [tracking summary contract](integration-tracking-status.md)
through the existing web service. It reads the configured authoritative JSON file
once per request, never a caller-supplied path. It performs no collection, audit,
move, rescue, NFS operation, configuration write or SQLite activation.

## Authentication and configuration

The endpoint is disabled by default (HTTP 404). Configure the container environment
variable `INTEGRATION_API_TOKEN` with a dedicated random secret, 32–256 characters
from ASCII letters, digits, underscore and hyphen. A suitable generator is
`python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
Short or malformed configured values leave the endpoint disabled.
Do not reuse Jellyfin credentials, the dashboard session secret or an administrator
password. Keep the token in private deployment secret/environment configuration,
not a URL, tracked file, screenshot or shared command output.

Clients send `Authorization: Bearer <token>`. Missing/incorrect credentials return
HTTP 401 and `WWW-Authenticate: Bearer`. Browser login sessions and query-string
tokens are not accepted. The integration token grants no dashboard login or action
permissions. Existing dashboard authentication remains independent.

Replace the configured token and restart/recreate every web worker/container to
rotate it; update clients afterward. There is no old-token grace period or token
management endpoint. Changes to an environment file alone cannot modify running
process environments. Use HTTPS for access across untrusted networks; the app
adds no TLS termination, permissive CORS or public exposure on your behalf.

## Audit coordinator status

`GET /api/v1/audit-status` uses the same dedicated token and no-store policy.
It returns one coordinator snapshot projected onto a fixed schema: `running`,
`queued`, `rescuing`, `last_result`, `last_started`, `last_finished`, and
`next_run`, plus schema/read-only/authorization metadata. Results are restricted
to `completed`, `failed`, or null. Valid timezone-aware timestamps are normalized
to UTC; naive, malformed or unavailable values become null. Unknown flags return
HTTP 503 with null fields, never a falsely healthy idle state.

The source is `coordinator_snapshot`, combining current process flags with the
existing best-effort historical reader. Missing/unreadable historical records
can leave last-run fields unknown even when current flags are available. This
endpoint does not certify durable history completeness, active collectors,
mount availability or a recent successful audit. `freshness_verified` remains
false. A `completed` result is the coordinator's recorded outcome, not an
independent validation of Jellyfin signals or every lifecycle operation.
It returns no action lists, free-text errors or media details.

## Responses

- HTTP 200: validated state, `status=advisory_only`; counts are tracking records,
  not live inventory or a unique collection total.
- HTTP 503: missing, invalid or unreadable state, `status=unavailable`; counts
  and pending-operation presence are null, rather than healthy zeros.
- HTTP 404: integration token absent or invalid in server configuration.
- HTTP 401: endpoint configured but bearer authentication failed.

Responses use `Cache-Control: no-store` and vary by Authorization. No titles,
paths, credentials or raw exceptions are returned. Freshness is explicitly
unverified; a successful HTTP response does not prove a recent successful audit
or available media mounts. Existing `/health` remains the public liveness check.
The summary grants no safety permit. JSON remains authoritative and all SQLite
production blockers remain in place.

Poll at a modest interval such as 60 seconds; this version rereads tracking JSON
for each authorized request. It adds no rate limiter or persistent cache. Custom
widgets may map `tracking_counts.waiting`, `holding`, `keep`, `removal` and
`arr_sync_pending`. Treat non-200 responses as unavailable. Vendor-specific
Homarr/Homepage [configuration examples](integration-widgets.md) are available;
actual renderer/cache compatibility remains pending testing on installed versions.

## Disposable Unraid smoke check

This uses the already installed auditor image's Python dependencies with the
reviewed checkout's code. It creates a separate container and temporary synthetic
state. It has no network, Docker socket, production media/state mounts or port
publication. It uses Flask's in-process test client, not a live listener. It does
not deploy a new image or change the existing auditor container.

```sh
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = "feature/sqlite" ]
  git pull --ff-only origin feature/sqlite
  lab_image_id=$(docker inspect --format '{{.Image}}' media_collection_auditor)
  docker run --rm --pull=never \
    --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --tmpfs /tmp:rw,nosuid,nodev,size=64m \
    --mount "type=bind,source=$PWD,target=/checkout,readonly" \
    --workdir /checkout --entrypoint python \
    "$lab_image_id" -B /checkout/scripts/integration_api_smoke.py
)
```

Expected status: `disposable_api_smoke_passed`. This verifies the isolated endpoint
contract with installed dependencies; it does not replace final release image
verification, actual widget integration or NFS ownership acceptance.

The authentication short-circuit and response headers follow the documented
[Flask request lifecycle](https://flask.palletsprojects.com/en/stable/reqcontext/).

Local validation, October 22, 2026: maintained regressions passed 680 tests and
19 subtests on macOS, including isolated copied-image runtime imports and API
contract tests. The synthetic smoke command passed locally. Unraid container
smoke acceptance and final release-image verification are still pending.


Acceptance update, October 22, 2026: the user reported
`disposable_api_smoke_passed` on Unraid for summary commit `6438482`, with no
network collection or production authorization. Its GitHub security workflow
reported success. The subsequent audit-status endpoint is tested locally;
the updated smoke script checks both routes using only synthetic state.

Audit-status increment validation: maintained local regressions passed 692 tests
and 19 subtests; copied-runtime endpoint checks passed separately (4 tests).
The updated disposable smoke passed within local regressions. No new production
or NFS test is required for this projection-only increment.


## Disposable HTTP transport check

`scripts/integration_api_http_smoke.py` exercises both endpoints over actual
loopback HTTP in a spawned process. It accepts no target/path arguments: state
and history are generated in a new temporary directory, credentials are random
fixture-only values, and the listener binds only `127.0.0.1` on an OS-selected
port. Requests use a direct connection without proxy, redirects or retries.
External Requests collection and action callbacks are blocked in the child.

Readiness has a 10-second limit and individual requests a 3-second timeout.
Cleanup terminates only the created child, joins for 3 seconds, then kills/joins
that child if required. Failure reports are redacted and exit nonzero. This is
a temporary Python WSGI reference server, not a production server configuration;
see the [standard-library WSGI reference documentation](https://docs.python.org/3/library/wsgiref.html#module-wsgiref.simple_server).
Its bind hook uses a fixed server name to avoid HTTPServer's reverse-DNS lookup.

The test verifies real status codes/headers, success-to-unavailable transitions,
empty versus missing/invalid tracking, historical-result redaction and denied
action authorization. It does not render widgets or certify dashboard caches,
TLS/reverse proxies or cross-container DNS/networking.

Run on Unraid using a separate container and installed image dependencies:

```sh
(
  set -eu
  cd /mnt/user/sqlite_lab_checkout
  [ "$(git branch --show-current)" = "feature/sqlite" ]
  git pull --ff-only origin feature/sqlite
  lab_image_id=$(docker inspect --format '{{.Image}}' media_collection_auditor)
  docker run --rm --pull=never \
    --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --tmpfs /tmp:rw,nosuid,nodev,size=64m \
    --mount "type=bind,source=$PWD,target=/checkout,readonly" \
    --workdir /checkout --entrypoint python \
    "$lab_image_id" -B /checkout/scripts/integration_api_http_smoke.py
)
```

Expected status: `disposable_api_http_smoke_passed`,
`server_process_stopped=true`, and `widget_rendering_verified=false`. Container
loopback works with `--network none`; no host port, Docker socket, production
media/state or NFS control is exposed to this fixture. The container removes
itself after the fixture exits. No image pull, build or package installation
is required. The source checkout is mounted read-only.

HTTP-fixture local validation: 73 focused API, HTTP, snapshot, copied-runtime and
web-security tests passed on macOS. This includes five new transport/startup
checks. A broader run's final result was not captured after interruption and is
not claimed as a fresh full-suite pass. Production runtime code is unchanged by
this fixture increment; Unraid HTTP transport acceptance remains pending.
