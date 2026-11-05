# Feature roadmap

## Verified baseline

- Primary JSON tracking with preserved lifecycle clocks and unknown fields.
- Serialized daily/manual scans with one-hour cooldown and five actions per library.
- Fresh Jellyfin protection checks and verified Radarr/Sonarr updates.
- Durable move/import intents and explicit GET-only recovery.
- Modern left navigation, separate Review page, persistent Activity and History.
- Authenticated integration APIs, Movie/TV Homarr widgets and artwork links.
- Explicit existing-folder Arr imports, unmonitored with no download searches.
- Atomic settings application without typed confirmation phrases.
- Searchable, paginated complete scan decisions with explicit partial-history notices.
- Live scan phases, checked-title counts and elapsed time with no overlapping scans.
- Recursive video detection and opt-in metadata-only orphan quarantine with a 24-hour observation period.

## Next priorities

1. Observe successful scheduled and manual Movie/TV scans under the current caps.
2. Resolve stale tracking records and unmanaged folders through explicit review.
3. Validate configured notifications and backup/restore operations end to end.
4. Consider lifting move caps only after a separate reviewed rollout.

Removal deletion is opt-in with an explicit warning; season pruning remains unavailable. Neither source cleanup nor
successful moves enable destructive options. Season pruning will require its own
protection checks, previews, disposable testing and explicit approval.
