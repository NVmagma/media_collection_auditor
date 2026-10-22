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
Homarr/Homepage examples remain pending verification against those products.

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
