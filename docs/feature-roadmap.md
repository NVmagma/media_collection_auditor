# Feature roadmap

## Verified baseline

- Primary JSON tracking with preserved lifecycle clocks and unknown fields.
- Serialized daily/manual scans with one-hour cooldown and five moves per library.
- Fresh Jellyfin protection checks and verified Radarr/Sonarr updates.
- Durable move/import intents and explicit GET-only recovery.
- Modern left navigation, separate Review page, persistent Activity and History.
- Authenticated integration APIs, Movie/TV Homarr widgets and artwork links.
- Explicit existing-folder Arr imports, unmonitored with no download searches.
- Atomic settings application without typed confirmation phrases.

## Next priorities

1. Observe successful scheduled and manual Movie/TV scans under the current caps.
2. Resolve stale tracking records and unmanaged folders through explicit review.
3. Improve complete decision browsing, filtering and progress visibility.
4. Validate configured notifications and backup/restore operations end to end.
5. Consider lifting move caps only after a separate reviewed rollout.

Permanent deletion and season pruning remain disabled. Neither source cleanup nor
successful moves authorize enabling them. Any future deletion feature needs fresh
protection checks, clear previews, disposable testing and explicit approval.
