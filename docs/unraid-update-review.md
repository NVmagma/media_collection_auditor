# Read-only Unraid update review and application icon

The first update-reliability increment checks the **current** saved template
against the current container. It does not approve a replacement image, validate
a SQLite release binding, install a template or update Docker. A matching result
is not permission to use Unraid's Update/Apply with a different image.

From the checked-out repository on Tower:

```bash
bash scripts/unraid_update_review.sh
```

The helper uses the current cached image's Python runtime and the checked-out
review code, with no network or Docker socket inside the helper. Templates and
source are mounted read-only; private inspect data is piped directly to it.
Paste only the redacted JSON report. Exit status 2 means review is required.

Checks include duplicate internal `<Name>` values (even when filenames differ),
image digest drift, missing/changed mounts, unsafe preview flags, environment
values, read-only root and published ports. XML parsing failures are unknown
coverage and block a matching report. No credentials or host paths are printed.
The report cannot prove file stability against simultaneous administrator edits;
do not edit templates while collecting it.

If duplicate names exist, retain a private backup outside `templates-user` and
review which template matches the working container before removing an obsolete
entry. Renaming an XML file **inside** that directory does not remove its internal
name collision. This helper never makes that choice or changes files for you.

Next update milestones: compare a proposed replacement with the working binding,
produce a backup-first update plan, and rehearse DockerMan recreation before
providing a reviewed Tower update. Existing image/source-bound SQLite checks stay
in force; changing Repository alone is not a migration.

## Square app icon

`unraid/assets/media-collection-auditor-icon.png` is a square transparent PNG
adapted from the existing badge, with no text so it remains legible at small sizes.
The original wide badge remains available for dashboard branding.

The repository is private. Anonymous GitHub raw URLs cannot reliably supply
Unraid/Homarr icons, so do not put a GitHub access token in an icon URL.

Both explicit SQLite Docker recipes now include the icon at
`/static/auditor-icon.png`, accessible without a login. **The currently installed
image does not include this new asset yet.** After a separately tested image
update, a browser-reachable URL such as
`http://10.0.0.10:8089/static/auditor-icon.png` can be used in Homarr's application
icon field and the saved Unraid template's Icon field. The image URL requires no
API token. Use your own host/port for other installations.

For an icon that remains available while the auditor is stopped, serve this PNG
from another existing static web service and use that URL in both places. Keep
the URL free of credentials. Saving template metadata and recreating a container
are distinct operations; use the reviewed update procedure for recreation.

## Disposable Tower acceptance

The fixture builds a local preview image from committed bytes, then runs twenty-five
standard-library tests in a new container and a newly marked lab directory.
It needs no host Python, registry push, GitHub Actions minutes, Docker socket
mount, production paths or published ports. Static icon delivery is exercised
through the real Flask route over private loopback HTTP; no scheduler is started.

```bash
bash scripts/unraid_update_lab.sh /mnt/user/sql_test
```

Use an existing disposable parent. All fixture artifacts and build diagnostics
are retained in the new `unraid-update.*` directory. Only the newly created
container is removed at exit. A successful run ends with
`status=unraid_update_lab_complete`. This does not validate a production update,
SQLite rebinding, or DockerMan recreation. GitHub CI remains a separate check.

Local Docker acceptance passed twenty-five tests on 2026-10-26; the real fresh-preview suite also passed nine tests with binding-review checks. GitHub Actions could not
start because of its account billing/spending restriction; no CI pass is claimed.

## Proposed cached-image binding review

```bash
bash scripts/unraid_proposed_update_review.sh sha256:FULL_CACHED_IMAGE_ID
```

This separately requested read-only diagnostic runs a **new helper container**
from an explicitly selected cached image. Current auditor volumes are inherited
read-only, network is disabled, and no Docker socket is mounted. The candidate's
packaged activation validator receives the current private environment through
stdin; template values, credentials and binding contents are not printed.
No image is pulled, no production process is executed or stopped, and no binding
is created or edited. Do not use an untrusted image with private mounts.

A changed application source revision requires fresh reviewed preparation;
changing only the Repository field cannot reuse the old release binding.
Even when revisions match, the complete packaged validator must pass. Changes to
entrypoint, command, stop signal, declared volumes or preview profile are refused.
A successful diagnostic still says `update_authorized=false`: registry approval,
backup-first planning, template review and recreation rehearsal are separate.
The observation does not protect against concurrent administrator changes.

The disposable lab now includes proposed-update refusal cases. Actual matching
binding validation is also exercised in the fresh preview container fixture.


## Backup-first update progress

The new capture/inspection functions in `scripts/unraid_update_backup.py` are
currently exercised through disposable fixtures, not a production host command.
Capture validates the current preview and current template before writing a new
private logical backup packet. It preserves the complete authoritative tracking
snapshot (including clocks and extension fields), exact saved configuration,
retained JSON source, current binding, container inspection and selected template.
This is **not** a physical SQLite database copy or a writer-exclusion claim.

All files use private permissions. A durable request precedes payload writes;
a completion receipt is written only after a second current-binding validation,
unchanged input/snapshot checks and captured-content verification. Incomplete
packets stay incomplete and cannot be overwritten or automatically retried.
Inspection requires an explicitly selected receipt fingerprint and verifies every
captured file, refusing missing, corrupt or changed content. It never restores or
updates a container. Backups contain credentials; only redacted summaries may be
shared.

Local verification: 46 diagnostic/backup/preparation/transaction/launcher regression tests, twenty-five isolated
lab tests, and nine actual fresh-preview tests, including retained movie/TV clocks
and unchanged original files. Tower acceptance of the expanded lab is next.
Replacement binding preparation is covered by the next increment below. A backup-first
service transaction and its explicit recovery/recreation rehearsal remain outstanding.

## Replacement binding preparation (disposable acceptance)

`scripts/unraid_update_prepare.py` consumes a receipt-fingerprint-selected verified
backup and prepares **new empty private logs and control directories** using the
candidate image's packaged binding implementation. It preserves the complete
tracking snapshot and saved configuration values, including unknown extensions,
movie/TV clocks, schedule and API token. Only the three internal state/config/SQL
path bindings change. Saved JSON may be serialized canonically in the new copy;
the byte-exact original remains in the backup. Interpreter defaults are inherited
from the candidate image rather than copied from the old interpreter.

The old files are never edited. Tracking parity is checked at revision zero,
the candidate binding must pass its complete validator, and the selected backup
is rechecked before completion. Partial attempts remain marked and cannot replay.
A wrong image profile, modified backup, occupied destination or aliased root is
refused. Preparation performs no HTTP or Docker calls and never starts a worker.

The expanded disposable Tower lab exercises old-source to new-source preparation,
retained old-binding validation, interruption after binding, corruption and
unchanged clocks/settings. The actual fresh-image suite additionally exercises
preparation through the packaged implementation without altering the running
fixture's settings or state. `update_authorized=false` and
`backup_freshness_verified=false` remain explicit: source freshness at cutover,
reviewed replacement template/image references, service swap and recovery still
need their separate transaction and rehearsal. No production preparation command
is provided by this increment.

## Fixture container swap and explicit recovery

The transaction in `scripts/unraid_update_transaction.py` is explicitly
fixture-only: production service names are refused and no production launcher
exists. Scoped Docker acceptance admits only recorded new fixture IDs, labels,
images and mounts under its newly created private volume. No host ports are
published. The helper uses the Docker socket to control these fixtures; it is not
a sandbox against arbitrary code with Docker privileges.

The rehearsal stops and retains the original, starts the prepared replacement,
checks authenticated HTTP readiness, then updates a private fixture template.
Recovery is explicit: verify both tracking snapshots/configuration, stop/retain
the replacement, restore the private template and original name, restart the
original and verify HTTP readiness. Neither container is removed by the model.
The fixture harness cleans up only its recorded disposable containers afterward.

Every effect follows a durable intent. Fault tests cover lost stop/create
acknowledgements, failed health, diverged data, corrupted history and replay.
Uncertain creation requires an explicitly reviewed exact replacement ID; no name
search can authorize adoption. A separate real subprocess is killed with SIGKILL
after the durable old-stopped record. Its parent verifies the worker stays
stopped before explicitly requesting and verifying recovery.

Run the updated no-socket fault lab as before. To exercise actual fixture workers
and controller death, build the committed preview image and use the existing
scoped fresh-image fixture on Tower:

```bash
image=$(bash scripts/sqlite_preview_release_build.sh)
bash scripts/sqlite_preview_service_lab.sh "$image" fresh
```

This creates a new Docker-managed fixture volume and randomly named containers;
it does not inherit production mounts or touch Unraid templates. Both workers
use the same locally built fixture image; this is a service/recovery rehearsal, not a
cross-version compatibility or registry-publication claim. Different source
revision binding preparation is covered by the separate preparation tests.
Freshness at production cutover, reviewed registry references, managed-template
replacement, backup capture and production transaction orchestration still need
an explicit production implementation and review.

## Recovered TV preview and requested settings

The same-image recovery controller (`unraid_preview_recovery_start_host.sh`) is a
separate explicit transaction for an already stopped preview. It verifies the
selected backup, prepared roots, original tracking/settings/binding and unique
saved template before retaining the old container and starting the replacement.
It saves the replacement template only after authenticated API readiness. It does
not delete the old container, retry an uncertain effect or restore automatically.
This is the narrow recovery used for the TV-enabled preview, rather than a general
Unraid image-update implementation.

The settings protection changes require a newly accepted preview image. They do
not alter an older running image merely because source code was pushed. In that
new image, Settings saves a private `auditor_config.pending.json` beside the
active configuration. The active configuration and its state binding remain
unchanged. A persistent page notice lists only known setting labels, never secret
values, and identifies requests made against an older configuration. Inputs still
show active settings. Submitting another request replaces the pending request;
it does not apply or merge the previous request automatically.

A request needs explicit validation and application in a prepared preview before
it takes effect; this increment does not provide an automatic settings-application
controller. Media actions and season pruning cannot be enabled through this form.
If an administrator changes the bound configuration externally, preview scans
pause while the login and authenticated settings page remain available. Invalid
bindings return an authenticated API 503 rather than falling back to JSON state.
The SQLite database and retained source are never reset to restore availability.

Test the committed image on Tower using only a new disposable lab:

```bash
image=$(bash scripts/sqlite_preview_release_build.sh)
bash scripts/sqlite_preview_release_lab.sh "$image" /mnt/user/sql_test
```

This runs real application startup with missing and changed bindings, confirms
login remains available, checks authenticated API refusal, and verifies unchanged
tracking. It also exercises the normal bound preview API and clean shutdown. No
production mounts, service names, Docker socket or published ports are used by
the test container. A local acceptance result does not imply a successful GitHub
Actions build or published image.

## Applying a saved settings request (development preview)

The settings application workflow adds an explicit **Apply Requested Settings**
button for authenticated administrators. Saving a request still leaves the active
configuration untouched. Applying validates the exact displayed request digest,
its base configuration, allowed preview policy and media roots, then coordinates
with scans through the existing source and SQLite runner locks. An active scan
leaves the request waiting for another explicit attempt; application does not
queue a scan, clear daily claims or restart the container.

Only the saved configuration and its preview binding are replaced. Their staged
file identities and private before/after copies are retained in a settings
transaction directory under the private control root. The SQLite database,
retained JSON source, clocks, preparation receipts and media are unchanged. A
pending transaction marker blocks preview scans and tracking API responses while
login and administrator settings remain available. The running worker reloads
settings after successful application.

An interrupted application is never replayed or rolled back automatically. The
settings page offers **Restore Previous Settings**, which checks the retained
records, unchanged tracking and known file identities before restoring the old
configuration and binding. An interrupted restoration can be explicitly resumed
when its recorded file identities still match. Unknown replacements, corrupt
records or changed tracking require review rather than adoption. A restored
request must be reviewed and saved again before another application attempt.

The baseline environment used when an override is removed is captured before
saved settings are loaded, so removal returns to the original Docker value. The
form cannot enable media actions, permanent deletion, cross-filesystem moves or
season pruning. No environment switch opens the sealed build.

Before deploying this development workflow, run its disposable host-backed lab:

```bash
settings_image=$(bash scripts/sqlite_preview_release_build.sh)
bash scripts/sqlite_preview_settings_apply_lab.sh "$settings_image" /mnt/user/sql_test
```

The lab uses a new directory and container, private loopback HTTP, synthetic admin
credentials, real SQLite state and an actual controller SIGKILL. It verifies
settings application, interface availability after restart, explicit restoration,
and unchanged tracking bytes. Production media, appdata, Unraid templates, Docker
socket and published host ports are not mounted or changed. Only the fixture
containers/processes are started or stopped. This does not deploy the workflow or
claim a published image; GitHub acceptance/publication remain separate.

## Different-image preparation without a service handoff

The same-image recovery launcher must not be reused for a new image. After
exact-image acceptance, `unraid_update_candidate_prepare_host.sh` can prepare a
new binding from one explicitly pinned logical backup:

```bash
bash scripts/unraid_update_candidate_prepare_host.sh \
  FULL_ACCEPTED_CANDIDATE_IMAGE_ID PRIVATE_BACKUP_PACKET RECEIPT_SHA256 \
  /mnt/user/appdata
```

This creates new private logs/control roots, preserves the selected logical state,
unknown fields, clocks, settings and environment, and validates the candidate's
packaged profile/revision. It uses a disposable read-only helper with only the
selected backup read-only, new roots writable, production media read-only for root
identity checks and the reviewed checkout read-only. The current auditor and old
appdata are never stopped, started, renamed, removed or written by this tool.

Success is `candidate_files_ready_not_started`. It explicitly reports no service
payload, no configured registry reference and no deployment authorization. It
cannot be passed to the same-image recovery start command. Existing/partial
roots cannot be reused or silently overwritten. Backup freshness at handoff is
still unverified and must be reviewed separately; continuing to run the old
preview does not make a previously captured packet current automatically.

First capture a new verified backup using `unraid_update_backup_host.sh` with the
current image's own packaged validator. Current container metadata is retained
inside the private packet, not pasted publicly. The controller supports older
images that lack the newer shared packet inspector by loading the inspector from
the trusted read-only reviewed checkout, never from backup contents. This path
was tested with actual e537ba5 application modules and synthetic packet data.

Registry publication and production handoff remain separate. The accepted local
ce58bd5 image need not be rebuilt for these controller-only preparation changes;
its packaged revision is checked when creating the new binding. Do not change
Unraid Repository or its saved template until an exact image reference and a
concrete replacement/recovery transaction have been reviewed.


Candidate host preflight normalizes blank lines in Docker's formatted mount
output before sorting and comparing the exact three binds. An extra bind still
blocks before new roots or helper execution. Every failed check now emits a fixed
step/reason diagnostic; no command text, private settings or environment contents
are printed. This fixes a silent exit observed during Tower preparation.

## Review the prepared candidate without changing services

Run `unraid_update_candidate_review_host.sh IMAGE PREPARED_ROOT BACKUP
RECEIPT_SHA256` after preparation. It creates a new private review directory and
compares the selected backup with the current container, saved template, retained
source/settings/binding and SQLite snapshot. It also validates the prepared
candidate using that image's packaged activation checks. All inputs are mounted
read-only; only the new review directory is writable. No Docker socket is mounted.

The private proposed container JSON and template XML preserve ports, environment,
resource options and read-only media. Candidate image labels and the WebUI link
are updated in the proposal. The image reference remains
`@APPROVED_PREVIEW_REFERENCE@`: these files cannot be used as an executable
handoff. The helper never publishes an image, changes templates or controls the
current auditor. Do not paste private proposal files; share only the redacted
report and directory path.

`backup_matches_current_observation` describes a comparison at review time, not
writer quiescence or permission to deploy. Any changed input blocks completion;
partial output is retained and never overwritten. The completion receipt is
written only after both database captures verify and close. A later handoff
still needs a fresh validation, an exact published reference and an explicit
service transaction with recovery. The stopped same-image recovery guard remains
unchanged.

After publication, an optional fifth argument to the review host helper selects
an immutable GHCR digest. Docker must resolve that reference to the exact cached
candidate ID, and image inspection must list it in RepoDigests. The newly created
private proposals then contain that digest in both Image and Repository. Tags or
unverified digests are rejected before proposal writes. The report says
`verified_cached_digest`; deployment authorization remains false. This is still
a review, not a container execution or template installation command.

## Candidate handoff and explicit recovery rehearsal

`unraid_update_candidate_handoff.py` now provides the single-attempt service
transaction separately from the stopped same-image recovery launcher. It verifies
the original, records durable intent, stops it, revalidates data offline, retains
it under a reserved archive name, creates/starts the replacement and verifies
health before installing the managed template. Exceptions never trigger retries,
container removal or automatic restoration. Explicit recovery requires the exact
replacement ID and unchanged data, retains the replacement, restores the original
template and name, and starts the original only after those checks.

The existing fresh service fixture now exercises these shared functions through
a scoped adapter. All real Docker names, IDs, labels and mounts are restricted to
the newly created fixture volume; the production service name is only a normalized
in-memory validation role. The adapter cannot access production containers.
Run `sqlite_preview_service_lab.sh ACCEPTED_IMAGE_ID fresh` on Tower for the
actual handoff/recovery rehearsal. No production execution launcher is supplied
by this increment; host input verification and explicit recovery wiring must be
completed before using the transaction against the current auditor.
