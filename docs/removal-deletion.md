# Whole-title Removal deletion

Removal deletion is an explicit opt-in, disabled by default. TV season pruning,
direct filesystem deletion and cross-filesystem moves remain unavailable.

## Enable deliberately

1. Back up configuration and tracking, then run a preview with deletion enabled
   to inspect eligible Removal titles. A preview sends no DELETE requests.
2. In Settings → Safety, enable Allow Permanent Deletion and read the warning.
3. Check the acknowledgement and choose Apply Requested Settings. There is no
   typed phrase. Saving does not start a scan; live scheduled and manual scans
   use the setting. Dry Run must be disabled for execution.
4. The dashboard and manual scan confirmation show whether Removal deletion is
   enabled. At most one title per library per scan can be deleted initially.
   Those deletions share the existing five actions per library and ten overall;
   a busy library can exhaust its action slots before a deletion is attempted.

Every apply with deletion enabled requires acknowledging the warning again.
Disabling it clears saved consent. Setting only the Docker environment flag
cannot enable deletion without the saved acknowledgement. The worker rereads
current settings immediately before a destructive dispatch; changed settings
stop deletion instead of using old captured consent.

## What is deleted

Only a whole title already in Removal with its complete waiting period elapsed
is eligible. The minimum Removal period is one day. The auditor asks Radarr or
Sonarr to delete that exact unmonitored title with `deleteFiles=true` and an
import-list exclusion. All episodes of a TV series are included. The auditor
never falls back to `unlink` or `rmtree` on production media.

Treat this as irreversible. The auditor cannot restore files. Arr recycling-bin
settings can retain deleted files; the auditor does not claim that disk space
was reclaimed. Backing up tracking alone does not back up media. Import-list
exclusion prevents normal list re-import; it is not a universal download ban.

## Required evidence

- Complete fresh Jellyfin data, with no favorite, keep, keep-forever or
  keep-all-seasons protection. Favorites block deletion even when the legacy
  favorite-to-Keep move preference is disabled.
- One exact Arr record at the configured Removal path, unmonitored.
- An unambiguous Removal clock and no copy of that title in another stage.
- Stable descriptor-checked stage and title identities, complete contents,
  and no content newer than the Removal clock.
- No symlinks, hardlinked files, special files, nested mounts, unreadable
  directories or inventory exceeding the bounded traversal limits.
- A saved operation intent before a single DELETE request.
- Bounded GET polling (up to 30 seconds) for asynchronous Arr folder removal, then two independent Arr absence reads and absence from all four lifecycle
  stages before recording completion and removing the selected clock.

Neither unavailable protection data nor a missing Arr record grants permission.
A failed or uncertain outcome pauses further scans. The HTTP acknowledgement
alone never proves completion. Other titles' clocks and unknown tracking fields
are preserved.

## Interrupted outcomes

Operation review uses GET only. If the title and Arr record are both absent,
a fresh fingerprinted review can record that observed deletion without repeating
the request. If the entire original inventory and exact Arr record are unchanged,
and the journal proves no DELETE dispatch was started, review can cancel an unperformed intent. An attempted request cannot be canceled merely because files and the record still exist: Arr may still be processing it. Partial deletion, a changed title,
changed stage roots, an endpoint change or an unavailable service remains blocked
for investigation. No automatic retry or clearance is performed, and old scan
history is not rewritten as a successful attempt.

The protocol follows the official [Radarr v3 schema](https://github.com/Radarr/Radarr/blob/develop/src/Radarr.Api.V3/openapi.json)
and [Sonarr v3/v4 schema](https://github.com/Sonarr/Sonarr/blob/develop/src/Sonarr.Api.V3/openapi.json).
Disposable loopback tests validate request parameters, lost acknowledgements,
changed protections and actual controller death after the delete response.
