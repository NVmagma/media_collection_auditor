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
- Private browser backups, restore-copy verification and an isolated packaged recovery rehearsal.
- Administrator delivery tests for saved notification destinations.
- Read-only Tracking Review for local clock/folder mismatches, possible name variants and recorded Arr issues.
- Dedicated admin Cleanup Review with recorded observation intervals, blocker reasons and quarantine locations.
- Recursive video detection and opt-in metadata-only orphan quarantine with a 24-hour observation period.

## Next priorities

1. Observe successful scheduled and manual Movie/TV scans under the current caps.
2. Add separately reviewed reconciliation for stale tracking records; complete fresh Arr management coverage remains future work.
3. Consider lifting move caps only after a separate reviewed rollout.

Removal deletion and staged TV season deletion default to off and have separate
warning acknowledgments. Season retention is opt-in. Staged season deletion
requires an expired Holding window and fresh Jellyfin and Sonarr checks.
