# Container maintenance review: Tower snapshot

The user supplied the selected-field review through `656679e`: 22 containers
observed, 11 flagged for review. This is a deployment example, not application
configuration or an ownership permit. No production enforcement is implemented
by this document. JSON remains authoritative and SQLite activation is disabled.

## Required controls to design

| Observed route | Review / control requirement |
| --- | --- |
| Auditor: broad RW media bind | Coordinate current JSON audits and manual writers with the future exclusive maintenance owner; existing locks do not exclude external writers |
| Jellyfin: broad native RW bind and nested union Movies/TV binds | Cover every overlapping mount; a read-only parent alone cannot cover writable nested mounts. Keep fresh real protection reads available while denying media writes; the synthetic HTTP fixture does not establish Jellyfin compatibility |
| Radarr/Sonarr: broad media and download binds, restart always | Quiesce automatic writers and prevent start/recreation throughout ownership. Required Arr API/reconciliation ordering must be reviewed separately; stopping containers alone is not an accepted integration model |
| MakeMKV: stopped, privileged, devices, broad RW media, restart always | Stopped state is not a fence. Review elevated access and prevent activation/recreation; a media mount policy alone does not account for privileged/device routes |
| Lidarr: stopped, broad native RW media, unless-stopped | Keep the writer excluded, including explicit starts/recreation; do not infer an ownership permit from its stopped state or restart policy |
| NZBGet: RW media-root descendants, restart always | Resolve overlap with tracked content and possible shared content paths before excluding it; include it in controls wherever the reviewed scope requires |
| Audiobookshelf: RW Podcasts descendant | Resolve actual lifecycle/content scope; the broad-root flag alone does not confirm a Movie/TV write route |
| Homarr: read-only Docker socket mount | Fence administrative API access during ownership; a read-only socket mount does not make API operations read-only |
| Homepage: read-only media plus read-only Docker socket mounts | Review media mount scope and fence administrative API access; media RO does not remove its separate control-plane route |
| SearXNG: writable cache volume | Resolve storage origin/scope; this generic volume flag is not confirmed media write access |

These are required properties, not executable stop lists or instructions to
modify restart policies. Broad/native/union aliases are explicitly declared in
the snapshot, not independently proven equivalent. Other host/share writers,
Unraid UI/API actions, custom jobs and changes after enumeration remain outside
this container snapshot. The operator has accepted an initial maintenance
window and a possible pause of all NFS shares as design choices only.

The user accepts temporary unavailability of both Homarr and Homepage during
the initial maintenance window as a design choice. No permission to pause
dashboards, NFS, Arr, Jellyfin or the auditor is implied. Dashboard pause does
not cover other administrative entry points or boot/restart behavior; these
still require an accepted model.

## Advisory report changes

The initial reviewer counted a mount as overlapping itself. This duplicated
`writable_destination_overlap` on ordinary single RW media mounts. The corrected
review retains their direct write warning and reserves destination-overlap
warnings for distinct mounts, including nested RO/RW configurations.

Each flagged container now lists categorical `control_requirements`, separating
media write routes, administrative API routes, elevated host access and unknown
volume scope. These categories neither select commands nor declare controls
verified. The report explicitly sets `enforcement_supported=false`, and all
production/exclusion/continuity fields remain false. A clean-looking lexical
snapshot cannot grant clearance.

This refinement is covered by local regression tests. The existing Tower
snapshot is sufficient for this design review; another server run of the same
inventory is not required solely to accept the wording/classification change.


## Disposable control-client pause test

The private control lab uses a Unix HTTP fixture that can only increment a
counter. It never mounts or contacts Tower's Docker API socket. The new client
receives a read-only socket-file mount and read-only command/source mounts,
then proves it can dispatch one fixture action. This tests socket communication
through a read-only mount without exposing actual daemon administration.

A controller process pauses only that new client container and is killed.
The independent supervisor then requests a second fixture action, verifies
that the private API remains responsive from another process, and requires the
counter to remain one and the client to remain paused. The existing connection
is retained across the pause. Cleanup kills the private endpoint before removing
the paused client so a cleanup-time thaw cannot make the pending action execute.
If endpoint cleanup fails, the paused client is retained and the harness fails.
Fixture files remain for review; requests are never automatically retried.

This is a bounded Docker-pause/controller-death scenario. It does not establish
restart inhibition across Docker/host restarts, prevent explicit unpause or
recreation by other administrators, test real dashboard behavior, or close
Gate 6. Every production/exclusion claim remains false. Both new containers
use the cached Python image, no external network, read-only roots, dropped
capabilities and restart policy `no`; no existing service is targeted.
