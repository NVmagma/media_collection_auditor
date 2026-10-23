# Read-only API deployment preparation

This deployment scope is the read-only integration API on `feature/sqlite`, not
SQLite production activation. JSON remains authoritative. There is no SQLite
migration, production media move, deletion or NFS control in this deployment.
Gates 6–10 remain open. Temporary widget fixtures are not real-state deployment.

## Candidate image

The existing manually dispatched Docker workflow now treats `feature/sqlite` as
a candidate release path. It runs the complete tests directory on Linux, builds
an amd64 image, scans it with the existing high/critical-fixable vulnerability
policy and smokes the actual image in both normal and read-only service modes
before publishing a commit-specific `api-candidate-<full-sha>` tag. It records
the repository digest as a workflow artifact. Deployment must pin that digest;
a commit-specific tag alone is not immutable or an artifact attestation.

No automatic push trigger was added for this branch. The `feature-sqlite` and
`latest` tags are not moved by this candidate path. The existing non-SQLite
branch publishing path is retained. No other branch is edited. The workflow is
explicitly dispatched using its branch revision; see
[GitHub's manual workflow documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

A workflow passing is an image acceptance step, not a production ownership
permit. Do not substitute the previously built security-scan image or installed
image tag for the accepted candidate digest.

## Optional separate service

`READ_ONLY_API_SERVICE=true` makes the shipped `main.py` entrypoint run only the
web server and exit before starting/importing an audit worker. The web application
allows only health and the two authenticated integration routes. Browser login,
settings, rescue, audit trigger, poster and experimental recovery views are
blocked. Its session key is ephemeral; it does not create a persistent key file.
Invalid service-mode values fail instead of falling back to an audit worker.
Default behavior is unchanged when the option is absent/false.

A separate process cannot see the existing worker's in-memory coordinator.
Accordingly `/api/v1/audit-status` returns HTTP 503 with null flags/result and
`source=coordinator_unavailable_in_read_only_service`. It must not report idle
or falsely reuse historical status as live running/queued information. The
summary remains available if its authoritative JSON input is valid. The current
Homarr template therefore displays counts plus an unavailable coordinator in
this deployment model; this is an explicit capability limit, not healthy idle.

A separate service can mount the authoritative state's parent directory at a
separate read-only path, with STATE_FILE selecting the existing JSON filename.
Mounting the directory rather than just one file allows atomic JSON replacements
to remain visible. It does not create a tracking copy, write the state or gain
media/API-service credentials. Configure a new dedicated integration bearer
credential privately; do not reuse a fixture token or the auditor's other keys.

Before choosing concrete deployment commands, confirm the desired service model,
the actual state path/mount and selected image digest. A separate-container
rollout can leave the existing auditor running and its image/config untouched.
Updating the existing container instead needs a preserved image/config rollback
and review of its effective dry-run settings because startup may schedule audits.

## Rollout boundaries

1. Complete local checks, publish the candidate deliberately, and verify its
   workflow/tests/scan/smoke results and digest.
2. Confirm authoritative JSON source and deployment choice using selected
   read-only metadata. Do not dump environment variables or credentials.
3. Start only the reviewed target service with the accepted digest. No default
   image update or auditor restart is implied by publishing a candidate.
4. Verify authenticated real-state summary and authentication failures. Observe
   unavailable coordinator semantics if using a separate process. Point widgets
   at it only after real-state reads are accepted.
5. Keep rollback scoped to that target. For a new sidecar, stopping/removing only
   that labeled container leaves the existing auditor and authoritative JSON
   untouched; retain its private credential/configuration for deliberate review.

Deployment choice: the user selected updating the existing auditor container.
The acceptance updates below record subsequent Tower rollouts; the optional
separate-service design remains available for other installations.

Local preparation validation (October 22, 2026): 739 maintained tests and 19
subtests passed on macOS with Python 3.12.14. This includes copied-runtime
entrypoint checks that reject worker import/session-key writes in read-only
mode. Workflow YAML syntax was checked locally; Linux full-suite, actual image
build/scan/smoke and publication are separate pending workflow evidence.

## Title-list deployment increment

The user selected an update to the existing auditor container and accepted its
aggregate API at the verified candidate digest
`sha256:f126c2cef077c50825f66583c12cb04e746e46fa505d9418307b1b2b038a0024`.
Both aggregate routes returned authenticated 200 and unauthenticated 401;
authority remained JSON and the selected saved settings reported DRY_RUN=true,
all deletion/cross-filesystem switches false. These are observations from that
rollout, not a permanent attestation of future configuration.

For the title increment, 79 focused tests passed on Tower. The user reported both
synthetic title previews working and supplied an oldest-waiting screenshot with
successful fetch and rendered cards, then requested deployment. Full ten-row
no-scroll board acceptance, empty/unavailable and stale-after-failure UI checks
remain unreported; do not claim those are complete. API fixture tests cover the
underlying empty/unavailable responses.

The next candidate must run actual-image smoke checks of both title routes in
normal and worker-free modes, including default-disabled, missing credential,
opt-in response and missing-state behavior. After acceptance, preserve the
currently deployed image as rollback, retain the existing integration token,
and add `INTEGRATION_API_TITLE_DETAILS=true` in the existing Unraid template.
That option intentionally permits authenticated title-name reads; keep boards
private as appropriate. Recheck the live safety settings and both authenticated
title routes before replacing widget fixture sources with the permanent auditor
URL and production integration credential. No SQLite cutover or NFS change is
part of this update.


## Artwork deployment increment

Tower accepted the title-list image at
`sha256:ec44a707a8d43227a53631983d855194adbc7a6f1bd3de339895d8979e5cc6a8`:
oldest-waiting returned ten of 522 records and leaving-soon four of four, both
with authenticated 200 and unauthenticated 401. JSON remained authoritative and
production activation disabled. The user reported real title widgets working.

The user subsequently reported the disposable artwork/click preview working.
This accepts the synthetic image/navigation path, not real Jellyfin matches,
poster access, complete fallback rendering or no-scroll board layout. Local
artwork regression validation passed 804 tests plus 19 subtests. The candidate
image smoke covers synthetic media metadata in normal and worker-free modes
without contacting an external server.

For the existing-container artwork update, retain the integration token and
`INTEGRATION_API_TITLE_DETAILS=true`, and add `INTEGRATION_API_MEDIA=true`.
The saved Settings Jellyfin host supplies both private metadata collection and
browser poster/detail URLs by default, as requested. The user supplied
`http://10.0.0.10:8086` as the browser-facing address; do not hardcode it into
application logic. Only use `JELLYFIN_PUBLIC_URL` when a separate browser address
is needed. Preserve the previous image/state/config rollback and recheck effective
safety settings. No SQLite activation, NFS change or deletion permission is
introduced. After the verified candidate runs, verify actual matching, anonymous
Jellyfin image delivery and browser clicks before claiming real artwork accepted.
