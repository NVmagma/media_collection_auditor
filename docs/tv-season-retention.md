# TV season retention and deletion

Season retention is opt-in under **Settings → Libraries → Stage Older TV Seasons**.
It is independent of whole-show lifecycle moves and the legacy
`ENABLE_SEASON_PRUNING` option, which remains unsupported by the JSON worker.

## Tags and precedence

| Jellyfin show tag | Season behavior |
| --- | --- |
| `one-season` | Keep the latest regular season active and stage older regular seasons in Leaving Soon. |
| `keep-all` | Restore staged seasons and retain all seasons. Takes priority over `one-season`. |
| `keep-all-seasons` | Existing protection tag, also recognized for restoration. |
| `keep-forever` | Protect the whole show and restore staged seasons. |

Tags must be on the show itself. Favorites alone do not request season staging.
The latest season is the highest-numbered regular season with video files on
disk; an empty higher-numbered directory does not make it the latest season.
Season 0 and a Specials directory stay in place. Folders must use unambiguous
`Season N` names, such as `Season 1` or `Season 01`. Loose videos, duplicate season
numbers, symlinks, unknown contents, or uncertain show identity can block review.

## Prepare the season Holding directory

The default path is `/media/TV_seasons_leaving_soon`. `TV_SEASON_HOLDING_PATH` can
override it in the container environment. It must be outside every whole-title
lifecycle root and on the same mount/device as the active TV folder. Create the
root before enabling retention. The worker creates show subdirectories beneath it.

For Unraid, create it under the native media root already bound to `/media`.
Do not mount a `/mnt/user` version over this one child directory. A native `/media`
mount and an extra child bind can expose different mount identities and prevent
an atomic rename. See [installation](installation.md).

If your family should watch or browse staged seasons in Jellyfin, include this
root in a Leaving Soon library accessible to them. A successful filesystem move
does not configure Jellyfin libraries. Enable **Refresh Jellyfin After Audit** if
you want the auditor to request a library refresh after successful media actions.

## Staging and restoration

Each live scan can move one season per show, within the shared five-TV/ten-total
action limit and one-hour scan cooldown. A show with three old seasons may need
three scans. Whole-show actions pause while its seasons are staged.

The worker verifies current Jellyfin tags, exact Sonarr identity/path, local
folders, and saved settings. It unmonitors the selected season in Sonarr before
staging it and restores the prior monitoring flag when the season returns.
Individual episode monitoring overrides block the action because changing a
Sonarr season flag also changes its episodes' flags. Other seasons retain their
monitoring settings. Download searches are never requested by season retention.

**Library → TV Shows → Holding** has two groups:

- **Full Shows Leaving Soon** for entire shows in `TV_hold`.
- **Seasons Leaving Soon** for staged seasons, with show posters, season numbers,
  staging dates, and grace-period deadlines.

Deadlines use the current **Holding Days** value. Changing that setting changes
existing displayed deadlines and deletion eligibility. To restore seasons, replace
`one-season` with `keep-all` and run or wait for a live scan. Restoration also
uses one season per show per scan. A completed move has a persistent season record.
A proposal or a visible Jellyfin tag alone does not prove that files moved.

## Optional season deletion

**Permanently Delete Expired TV Seasons** defaults to off under Settings → Safety.
It requires season retention to be enabled, at least one Holding day, its own
warning acknowledgment, and live mode. This setting is separate from whole-title
Removal deletion. Existing settings survive container updates.

At most one staged season can be deleted per scan, within the remaining shared
action slots. The worker requires all of the following:

- The staged season has completed the current Holding grace period.
- The show still has `one-season` and no favorite, keep, all-season, or permanent
  protection. A restoration decision takes priority.
- A higher regular season with video is still present in the active show.
- The staged directory matches its saved identity and recorded media fingerprint.
- Fresh Sonarr season and episode reads confirm it remains unmonitored.
- Current settings and contents still match immediately before the operation.

Deletion is permanent filesystem removal of the isolated staged season. It is
not an Arr whole-series DELETE and does not use Sonarr's recycling bin. A private
isolation directory and durable intent precede removal. The latest season,
Specials, other shows, and active whole-show lifecycle clocks are preserved.

Older test-image staging records lack the media fingerprint needed for deletion.
They remain ineligible. Restore them with `keep-all`, then stage again with
`one-season` to record the fingerprint and begin a new grace period.

## Interrupted outcomes

A retained season-move intent pauses scans. **Operation Review** can acknowledge
an already completed staging/restoration after checking the original directory
identity, media fingerprint, and two fresh Sonarr monitoring reads. It does not
repeat the rename or send another monitoring update.

An interrupted season deletion requires manual review. The journal stays pending,
and any partially removed files remain in the recorded `.season-delete-*`
isolation directory. There is no automatic replay or browser clearance for that
case. Preserve the appdata and remaining files for investigation.
