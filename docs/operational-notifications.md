# Opt-in operational failure notifications

The JSON worker can send two fixed event types:

- `scan_blocked_or_uncertain`: a scheduled/manual attempt failed, returned a
  non-completed outcome, or could not proceed after configuration validation.
- `settings_review_required`: preview settings/binding need review, or an
  authenticated Settings application/restoration failed. Routine lock-busy
  responses do not send alerts.

Use Settings → Notifications to configure Discord, ntfy or a custom webhook.
Explicitly enable `NOTIFY_OPERATIONAL_FAILURES=true` (default false). Preview
alerts also require `NOTIFY_ON_DRY_RUN=true` (default false). Existing legacy
JSON audit digests and leaving-soon notifications remain separate and unchanged.
No real target is enabled or contacted by the disposable acceptance script.

Messages contain only a fixed event code/description, observation timestamp,
preview flag and `media_actions_authorized=false`. They contain no exception
text, title names, user identities, media paths, settings payloads, credentials,
callback URLs or operation IDs. Discord mentions are disabled. ntfy uses an
optional configured Bearer token in its header, never the message body. Custom
webhooks receive versioned JSON; Discord/ntfy receive their supported formats.

HTTP(S) destinations reject URL userinfo, fragments, invalid ports and control
characters. ntfy header values reject injection characters. Requests use fresh
sessions with environment proxies disabled, redirects disabled and bounded
connect/read timeouts. Delivery is synchronous and can briefly delay failure
reporting; up to three configured targets are attempted independently. Transport
exceptions are redacted and cannot change scan/settings transaction outcomes.
No notification is sent while a media or settings transaction lock is held.

One attempt is allowed per event/destination incident in the current process,
marked before transport even when delivery fails or acknowledgement is uncertain.
There is no automatic delivery retry. Repeated scheduler failures do not send a
message on every 30-second wake. A successfully completed attempt rearms scan
alerts; an ordinary waiting cycle does not. Valid configuration or successful
settings apply/restore rearms the settings-review event. This suppression is
bounded, process-local memory, not an exactly-once durable delivery guarantee;
restart or destination changes can result in another message.

The worker retains its last validated notification settings if reload/validation
fails. Before the first successful validation only initial container values are
available, so invalid startup configuration cannot adopt unvalidated saved
notification destinations. A failed Settings apply uses the values captured
before the transaction, never the submitted pending destination. Alerts do not
clear intents, change replay claims, retry scans, initialize state or restore
settings/services. Notifications can themselves fail; use Scans/Settings and
redacted worker status for authoritative operator review.

## Test saved delivery

In Settings → Notifications, apply your changes, then select the test button for
the destination you want to check. Each click sends one labelled test to that
saved destination. Manual tests work in dry run and with automatic alerts
disabled. The delivery result reports whether the receiver accepted the request.
Check your channel or receiver to confirm the message arrived.

## Disposable Tower acceptance

Run `bash scripts/operational_notifications_lab.sh EXISTING_LAB_PARENT` from the
updated development checkout. A new isolated receiver tests real loopback POSTs
for all three formats, disabled/dry-run suppression, failed-delivery suppression,
redirect refusal and incident rearming. Only fixture code/files and a new
container are used. No production media, appdata, tokens, service/socket mounts,
external network connections or host ports are used.
