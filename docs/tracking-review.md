# Tracking Review

Administrators can open **Tracking Review** from the shared sidebar or the Review
coverage section. It compares local Movie/TV stage folders with saved JSON clocks.
Search, library/issue filters and 25-row pages make individual discrepancies visible.

The page distinguishes folders without their own stage clock, records whose exact
folder is in another stage, records without an exact match in readable directories,
duplicate stage folders, conflicting clocks, and possible case/Unicode name variants.
Possible variants are never adopted or merged. A missing match does not prove a
file was deleted. Unknown directories suppress absence claims rather than becoming
empty folders. Disabled libraries are excluded.

The saved settings' stage paths take precedence over stale environment defaults.
Local listings are bounded and repeated, and settings/tracking are reread for
consistency. Changes during observation show an unavailable comparison. This is
an advisory observation, not proof that external writers were excluded.

Arr rows are historical reasons recorded for selected lifecycle actions in the
latest retained scan. They are not a complete or current catalog of unmanaged
folders. Missing history is labelled unknown. Opening or filtering this page sends
no Arr/Jellyfin requests, edits no timestamps, and performs no import or recovery.
Links lead to the existing import and recovery flows, which require their own fresh
checks and explicit actions. No dates are reset, records pruned or media moved.

Use **Check current Arr coverage** to compare a library’s four local lifecycle
stages against its saved Radarr or Sonarr catalog. Each submission reads one
catalog. Results distinguish exact paths, similar folder names at different
paths, multiple matches and unmatched folder names. Review provider identity
through the separate import flow.

For a record without an exact folder, **Review clock for archival** checks all
four stages for the selected library. An administrator can then archive a single
clock after a fresh check under the scan lock. The original date and stage stay
in the JSON state archive. A returning folder starts a new active clock.
Existing archived entries, conflicting clocks, unreadable directories, name
variants and pending operations require separate review. Archival makes no
media changes or Arr requests.

**Archived tracking clocks** lists preserved records by title and library.
It shows the original saved lifecycle date and the time of archival in UTC.

**Preview TV season retention** checks one exact active show folder against
Jellyfin tags, Sonarr identity, local seasons, and any staged-season records. It
displays staging/restoration candidates without performing them. See
[TV season retention](tv-season-retention.md) for the opt-in live worker and
separate deletion controls.
