# Import existing media into Arr

This administrator-only flow registers an existing configured library folder with
Sonarr 4 or Radarr 6 through their v3 API. It is separate from lifecycle scans.
It never automatically adds unmatched titles, issues download searches, moves
media, changes lifecycle clocks or resets hourly/daily scan claims.

Open **API setup → Review an existing-media import**. Load folders and quality
profiles, enter the existing folder name, search for its movie/series, select the
correct TMDB/TVDB match and choose an existing quality profile. No provider match
or quality profile is selected automatically. Review the exact path and metadata,
then select **Import existing title**. The review expires after ten minutes.

The current Waiting, Holding, Keep or Removal stage is preserved. The selected folder
must contain nonempty supported media files, have no symlinks/special entries,
and occur in exactly one configured stage. The review identifies that stage;
ambiguous copies in multiple stages block registration. Review traversals are bounded to
20,000 entries, 16 directory levels and ten seconds per verification. The first
1,000 folders populate autocomplete; any exact configured library folder name can still be
entered. Lookup results are limited to 20; refine the search when truncated.

Both imports are unmonitored, with no immediate searches. Sonarr seasons are
unmonitored and new-item monitoring is `none`; Radarr collection/movie monitoring
on add is `none`. The selected quality profile is explicit and its configuration
is included in the review fingerprint. A later lifecycle transition or manual
change in Arr may change monitoring; this flow does not override those policies.

The current stage's root must already be accessible and registered in Arr.
Configured `RADARR_APP_*_PATH` / `SONARR_APP_*_PATH` aliases are used for remote
non-Waiting paths; the actual local folder remains pinned in its configured stage.
An existing provider ID or matching folder anywhere in that service blocks
creation; path conflicts are not repaired automatically. Payloads are built from
allowed fields, rather than forwarding raw lookup responses. No remote payload,
connection credential or exception text is rendered into the review.

The API shapes are checked against the official [Sonarr v3/v4 definition](https://github.com/Sonarr/Sonarr/blob/main/src/Sonarr.Api.V3/openapi.json)
and [Radarr v3 definition](https://github.com/Radarr/Radarr/blob/master/src/Radarr.Api.V3/openapi.json).
The initial compatibility gate accepts Sonarr major 4 and Radarr major 6,
matching the reported Tower versions 4.0.20.3014 and 6.4.4.10685. Other major
versions require compatibility testing before this flow can import into them.

## Persistence and uncertainty

Apply requires the immutable live profile and valid execution binding. Preview
may prepare a review but cannot create a record. Administrator sessions, request
origin and CSRF checks protect every POST; read-only integration tokens cannot
use these routes. Browser consent is exact, expires and is consumed per attempt.
The backend freshly rebuilds the review under both JSON-source and SQLite-control
worker locks; changed media, settings, tracking revision or quality profile refuse
before the POST. The single-use transport has no redirects, proxy inheritance,
automatic retries, arbitrary routes or search/rename/delete commands.

Before its one creation request, the controller checkpoints an `arr_import`
intent. The response is an acknowledgment, not proof. A new catalog read finds
the unique provider ID and two independent per-record GETs verify full path,
quality profile and disabled monitoring. Only after this proof and renewed local
checks does one guarded CAS clear the intent. Clocks, unknown state, unrelated
Arr queues, retained JSON and all scan claims remain unchanged.

The success scope is **Arr record registration**, not completion of Arr's
background file scan or inventory freshness. The UI states that Arr may still be
scanning. It does not declare a lifecycle scan completed or start one afterward.

If the request/acknowledgment or commit becomes uncertain, the retained intent
blocks further execution. Do not repeat the creation request, remove the intent
or restore an old tracking snapshot. **Verify a pending import** performs fresh
GET-only verification; **Acknowledge verified import** repeats that verification
and clears only the exact reviewed import intent. It never sends another POST.
An absent/mismatched remote record cannot be cleared by this procedure: inspect
the service and retained state, and resolve the association explicitly. Other
pending operation kinds require their own recovery procedure.

Local acceptance uses disposable bound SQLite, media folders and loopback Arr
servers for both services. Tests cover changed/expired reviews, duplicate IDs or
folders, unmonitored/no-search payloads, readback mismatch, lock contention, lost
acknowledgments, actual SIGKILL and explicit GET-only recovery. Chromium fixtures
exercise review, invalidation after edits, explicit apply and narrow layouts.
Production installation and real-server import validation remain deployment work.
