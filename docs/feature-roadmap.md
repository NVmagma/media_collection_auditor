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
- Private browser-created tracking/settings backups, integrity verification and inert restore-copy tests.
- Read-only Tracking Review for local clock/folder mismatches, possible name variants and recorded Arr issues.
- Dedicated admin Cleanup Review with recorded observation intervals, blocker reasons and quarantine locations.
- Recursive video detection and opt-in metadata-only orphan quarantine with a 24-hour observation period.

## Next priorities

1. Observe successful scheduled and manual Movie/TV scans under the current caps.
2. Add separately reviewed reconciliation for stale tracking records; complete fresh Arr management coverage remains future work.
3. Validate configured notifications and separately rehearse full service recovery; inert backup-copy verification is delivered.
4. Consider lifting move caps only after a separate reviewed rollout.

Removal deletion is opt-in with an explicit warning; season pruning remains unavailable. Neither source cleanup nor
successful moves enable destructive options. Season pruning will require its own
protection checks, previews, disposable testing and explicit approval.
