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

The fixture builds a local preview image from committed bytes, then runs ten
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

Local Docker acceptance passed ten tests on 2026-10-26; the real fresh-preview suite also passed nine tests with binding-review checks. GitHub Actions could not
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

Local verification: 31 diagnostic/backup/launcher regression tests, ten isolated
lab tests, and nine actual fresh-preview tests, including retained movie/TV clocks
and unchanged original files. Tower acceptance of the expanded lab is next.
Creating the replacement binding, a backup-first service transaction, and its
explicit recovery/recreation rehearsal are still outstanding.
