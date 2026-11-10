# Feature roadmap

This roadmap describes the JSON release on `main`. Image updates use the
explicitly promoted `ghcr.io/nvmagma/media_collection_auditor:stable` tag.

## Released

- Persistent JSON state, preserved clocks/extensions, serialized scans, and recovery journals.
- Daily schedules, manual live scans, preview mode, one-hour cooldown, and five actions per library.
- Fresh Jellyfin protection and exact Radarr/Sonarr path checks before media actions.
- Left navigation, table/poster views, title details, progress, persistent History,
  and searchable complete scan results.
- Tracking Review, current Arr folder coverage, explicit stale-clock archival,
  and searchable archived-clock history.
- Explicit unmonitored existing-folder Arr imports with download searches disabled.
- Private browser backups, restore-copy checks, and packaged recovery rehearsals.
- Recoverable metadata-only orphan quarantine and a dedicated Cleanup Review.
- Read-only authenticated APIs, Homarr/Homepage examples, and saved notification delivery tests.
- `one-season` TV staging, `keep-all` restoration, and separate full-show/season Holding views.
- Separate default-off consent for whole-title Removal deletion and expired staged-season deletion.

## Next priorities

1. Improve visibility of season actions skipped during preflight, including mount
   mismatches, episode monitoring overrides, and incomplete service observations.
2. Add clearer preview and integration/API representation of individual staged
   seasons. Current title-list widgets expose whole-title Holding records.
3. Expand interruption recovery for season deletion; it currently requires manual review.
4. Continue validating backup recovery, notification delivery, and scheduled/manual
   operations across supported deployment layouts.
5. Extend first-run and upgrade coverage for the template-only Unraid deployment.
6. Consider higher action limits only after a separate tested rollout.

Roadmap items are proposals rather than a delivery schedule. Deletion safeguards,
unknown-state handling, persistent clocks, and disposable testing remain release
requirements.
