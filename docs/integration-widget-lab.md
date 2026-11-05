# Expiring dashboard API fixture

This is a new disposable API instance for widget preview, not an auditor
container update. It uses the installed auditor image's dependencies with the
checkout mounted read-only. The user confirmed both `homepage` and `homarr` are
on Docker's default `bridge`. The launcher checks those bindings and refuses if
bridge container communication is explicitly disabled. It does not repair or
change networking.

## What it starts

`bash scripts/integration_widget_lab.sh sample` creates a new container with a
unique name and fixture label. It joins only the existing bridge and publishes
no host port. Other reachable bridge peers can contact its internal IP; its two
read-only routes require a new fixture-only bearer credential. Default bridge
DNS is not assumed: use the printed IP URL from server-side widget requests.

The container has a read-only root/checkout, dropped capabilities, no-new-privileges,
a 128 MiB memory limit, 64-PID limit and small writable `/tmp` tmpfs. The only
other bind is a newly generated credential file, read-only. There is no Docker
socket, real config/state/history, media mount, collector or audit worker.
The small fixture Flask application reuses production authentication/status
helpers but exposes only the summary and audit-status GET/HEAD routes. It does
not import the production web application's action handlers or `main.py`.

All responses representing data carry `fixture_only=true`; production activation
and authorization stay disabled. Errors do not include raw exceptions. Three
startup scenarios are supported:

| Scenario | Summary | Audit observation |
| --- | --- | --- |
| sample | Waiting=2, Holding=1, Keep=1, Removal=1, Arr pending=1 | Synthetic idle flags and recorded completion |
| empty | Valid zero tracking counts | Idle flags, unknown prior result |
| unavailable | HTTP 503, null counts | HTTP 503, unknown flags |

Each startup uses a fresh temporary dataset and credential. There is no network
scenario-change endpoint. The launcher does not stop an earlier fixture to create
another scenario. Failed readiness stops only the newly created labeled container.

## Lifetime and credentials

The instance expires after 900 seconds and has no restart policy. A process alarm
terminates it even if a client stalls while sending HTTP data. Hard expiry may
skip Python cleanup, but all synthetic data is inside container tmpfs and Docker
`--rm` removes the stopped container. No external resource is automatically restored.
The launcher’s new `/tmp/auditor-widget.*` directory and mode-600 credential file
remain on the host for review; no recursive filesystem cleanup is performed.
The credential grants access only to this temporary synthetic instance.

Read the printed `token_file` privately when entering the bearer credential in
a widget source. Do not post its contents in chat or commit it. Do not reuse an
existing production token. The launcher output contains the file path, never the
credential itself. The output's internal URL is for the dashboards' server-side
requests; it need not be reachable from the Mac browser.

## Start on Unraid

```sh
(
  set -eu
  cd /mnt/user/auditor_checkout
  [ "$(git branch --show-current)" = "main" ]
  git pull --ff-only origin main
  bash scripts/integration_widget_lab.sh sample
)
```

Expected output includes `widget_fixture_ready=true`, `fixture_only=true`,
`fixture_url`, `container_id`, `token_file`, and `lifetime_seconds=900`.
No image is pulled/built and no package is installed. No existing container is
started, stopped, restarted or reconnected. No NFS operation is performed.

## Preview acceptance remains separate

After startup, use the complete Homarr import candidate from
`examples/integrations/homarr-widget.example.json` for a new temporary definition.
Configure its `default` source with the printed URL, private network scope and
new fixture bearer credential, then validate/preview. Match the synthetic counts
above. A definition import/preview is a manual dashboard change; the launcher
performs none. Keep existing widgets and production API configuration intact.

Homepage's example is also available, but its live service/environment configuration
is not modified by this launcher. Acceptance must cover the unavailable/empty
scenarios and failure after a successful response before claiming correct stale
handling. The existing HTTP fixture does not substitute for widget rendering.

A server-ready response proves only that this new instance answered its own
loopback readiness request. It does not prove that either dashboard reached or
rendered it. Stop early only with the exact new container ID reported by the
launcher, or let the 15-minute deadline remove it. Never use broad stop commands.

This launcher targets the reported Tower network/container names. The product API
itself does not require the default bridge or these names. No media filesystem
choice is imposed by this lab.

Local validation: 91 focused fixture, launcher-policy, API, snapshot,
copied-runtime and web-security tests passed on macOS. Docker launcher checks
used inert stubs, and the fixture factory used Flask's test client. First actual
Unraid startup and subsequent Homarr import/preview remain unverified.

## Accepted Unraid startup and Homarr sample preview

The user reported `widget_fixture_ready=true` on the default bridge, scenario
sample, 900-second lifetime, and production_authorized=false. Docker reported
that memory limiting applied without swap-limit capability; no host setting was
changed in response.

The user then supplied a Homarr workbench screenshot showing two successful load
queries and the provided template rendering Waiting=2, Holding=1, Keep=1,
Removal=1, Arr pending=1, Running=No and Queued=No. This accepts authenticated
bridge reachability and the manually authored sample query/template preview for
the labeled Homarr revision. The definition was still unsaved. It does not prove
full-file import, saved-board polling, empty/unavailable rendering or stale-value
handling after an actual request failure. No production API deployment is inferred.

Next data checks can be started together without touching the sample instance:

```sh
(
  set -eu
  cd /mnt/user/auditor_checkout
  for scenario in unavailable empty; do
    printf '\nScenario: %s\n' "$scenario"
    bash scripts/integration_widget_lab.sh "$scenario"
  done
)
```

Each gets its own printed URL and private credential file. For each preview,
update the default source URL and credential together; do not reuse another
fixture's token. Unavailable should produce two failed load queries and explicit
unavailable/error rendering, never healthy zero counts. Empty should produce two
successful queries, all five counts zero, and an unknown last result. Neither
scenario establishes fresh real collection state. Both expire after 15 minutes.
