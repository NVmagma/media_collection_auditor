# Product roadmap

## Public-release storage portability

User requirement: users' filesystem choices must not be dictated by this one
Unraid deployment. Do not make native Btrfs, an Unraid-specific path, or a
filesystem-name blacklist a product prerequisite. Select behavior by verified
capabilities and retain explicit blocked outcomes when safety cannot be proven.

- Retain atomic no-overwrite rename as an optional fast path where supported.
- Build a portable exclusive-copy, verification, promotion and source-cleanup
  protocol with durable phases and restart handling. Do not replace a failed
  no-overwrite rename with ordinary overwriting rename.
- First building block: private copy staging on marked disposable fixtures,
  exclusive creation, recursive content verification, source retention and no
  tracking commit. This is not yet a completed move backend.
- Cover local, pooled, FUSE/user-share and cross-filesystem media paths with an
  explicit test matrix. Native filesystem results are controls, not a mandate.
- Separate media compatibility from SQLite database locking/durability. The
  database must have reliable locking, transactional writes and persistence;
  media can use a different storage backend. Never claim every network or
  filesystem implementation supplies guarantees it does not provide.
- Preserve pending state and explain missing capabilities. No filesystem label,
  successful copy, or configuration flag alone authorizes deletion or recovery.

No production mount change is approved or required by the current native lab
results. Gates 6–10 remain open while portable execution and integration proceed.

## Integration API for Homarr, Homepage and other clients

User-requested roadmap feature: a documented authenticated, versioned read-only
API for dashboard/service integration, independent of SQLite production activation.
Authenticated JSON tracking summary and redacted coordinator-status endpoints are implemented; see the
[API contract and disposable smoke command](integration-api.md). Readiness, version,
verified freshness and actual vendor widget acceptance remain planned.
[Configuration examples](integration-widgets.md) have been checked against
upstream documentation and the supplied installed image-label revisions.
A complete credential-free Homarr import candidate is available; import/renderer
acceptance remains open. See [version review](integration-widget-version-review.md).

Initial contract proposal:

- Versioned `/api/v1` endpoints for health/readiness, application version,
  lifecycle totals, last audit status/time and pending-work counts.
- Report active storage authority, dry-run/safety state, unresolved operation
  counts and data freshness so a dashboard cannot mistake stale/unavailable
  data for an empty healthy collection.
- Read one consistent authoritative snapshot: JSON while JSON is active and
  the verified SQLite store only after an approved cutover. No second tracking
  source or dashboard-specific state migration.
- Dedicated read-only bearer-token authentication, rotation and documented
  deployment handling. Define a minimal liveness response separately; detailed
  operational information requires authentication.
- No API keys, tokens, raw exceptions, media paths or user identities in the
  default response. Define opt-in title detail separately if later requested.
- Stable schema/versioning, documented error/status behavior, timestamps,
  unavailable states and practical polling guidance; provide sample Homarr and
  Homepage configuration against the finished contract.
- Contract tests for authentication, redaction, snapshot consistency, stale data,
  empty versus unavailable state, and JSON/SQLite parity.

Execution order: design the API contract and reuse the authoritative state
boundary; deliver authenticated read-only status/summary endpoints and tests;
then document widget examples. Audit triggers, configuration writes, media moves
and deletion are outside the initial read-only API and would require a separate
permission/design review.

## Visual dashboard widgets

User-requested direction (October 22, 2026): replace the initial plain-text widget
with a polished card layout inspired by the supplied reference. Use compact,
rounded rows, poster thumbnails, subdued backdrop artwork, clear title/year
hierarchy and aligned status badges. The reference is visual guidance, not a
request to copy its user identities or label every audit as completed.

Delivery stages:

1. Improve the existing summary widget with compact metric cards, lifecycle
   colors/icons, readable audit-status badges and a responsive layout. This can
   use the current aggregate API without exposing title details.
2. Design and implement an optional authenticated read-only title/artwork
   response for richer media rows: title/year, thumbnail/backdrop, actual
   lifecycle stage, protection indicators where verified, and relevant dates.
   Keep the default summary redacted. Artwork access must not expose Jellyfin
   credentials, media paths or tokens in browser URLs; define authorization and
   caching behavior for image delivery before implementation.
3. Build Homarr cards using supported runtime components and provide the best
   supported Homepage presentation. Do not promise identical layouts across
   dashboard platforms. Preserve a compact mobile view and artwork fallbacks.
4. Verify loading, empty, unavailable and stale displays before claiming visual
   completion. Use explicit unknown/unverified states; color must not be the
   only status cue. Never show retained values as a healthy current collection
   after a failed request. No audit/move/delete controls are added by this work.

The initial Homarr synthetic sample preview has passed. The unavailable and
empty fixtures have started on Unraid, but their widget preview outcomes have
not yet been reported. Visual polish is planned after these behavior checks;
it does not close any SQLite production gate or resume deferred NFS testing.
