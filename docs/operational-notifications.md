# Operational notifications

Use **Settings → Notifications** to configure Discord, ntfy, or a JSON webhook.
Enable `NOTIFY_OPERATIONAL_FAILURES` to receive alerts when a scheduled or manual
scan fails or returns an uncertain result. The option defaults to false. Alerts
in Dry Run also require `NOTIFY_ON_DRY_RUN=true`.

## Test saved delivery

Apply settings first, then use the destination's test button. Each click sends one
labelled test even if automatic alerts are disabled. A successful response means
the receiver accepted the request; confirm arrival in the channel or receiver.
Webhooks and ntfy credentials are secrets and should stay in private deployment
configuration or saved settings.

## Payload and delivery behavior

Messages carry a fixed event code/description, timestamp, preview flag, and
`media_actions_authorized=false`. They omit media titles, usernames, paths, raw
exceptions, and credentials. Discord mentions are disabled. ntfy optionally uses
a Bearer token. Custom webhooks receive versioned JSON.

Destinations use bounded timeouts, disabled environment proxies, no redirects,
and no automatic retry. One attempt is made per event/destination incident in the
current process, including failed or uncertain deliveries. A completed scan rearms
the scan incident. Restarting the worker resets this in-memory suppression.
Notification failures do not change scan results or clear pending operations.

The notification module also defines `settings_review_required` for callers that
emit it; the current JSON worker automatically emits the scan-failure event.
Configuration/startup failures that prevent entering a scan may require reviewing
container logs directly. Legacy audit-digest settings remain present, but the
serialized worker's automatic path does not deliver the legacy per-title leaving-soon
digest. Use the dashboard/API for those lists.

## Disposable delivery test

From a committed Linux checkout, run:

```bash
bash scripts/operational_notifications_lab.sh /path/to/existing/lab-parent
```

The lab uses new files and a new container, with loopback receivers for all three
formats. It checks suppression, failed delivery, redirect refusal, and incident
rearming. It uses no production appdata/media, service credentials, published
ports, or real notification destinations.
