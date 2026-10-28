# Combined interface/API preview release review

Scope: `feature/interface-api` into a new versioned **preview-only** image.
This review does not merge branches, publish a registry tag, change Tower,
turn on notifications, or enable media moves/deletion.

Included work:

- Hybrid dashboard, compact Overview, separate Review page, Library search/details,
  Scans/History presentation and accessible mobile layouts.
- One guarded Apply Requested Settings action, retained transaction/recovery
  protections and local-only draft indicators.
- Administrator integration setup, authenticated readiness and explicit errors.
- Aggregate coverage API, bounded process-local scan/proposal APIs, selected
  backup integrity status and default-off redacted operational notifications.

Disposable Tower evidence is recorded for coverage (8225f86), scan observations
(8429c3e), backup status (32ce7bb) and notification delivery (a6fc8c0): five HTTP
cases each passed without production mounts/services. API setup and preceding
Dashboard directions received user visual acceptance. This is source/runtime
acceptance evidence, not deployment of the combined image.

## Combined source verification (2026-10-28)

The full Linux disposable regression run passed **3,656 tests and 98 subtests**.
All four private-loopback HTTP/delivery suites passed (20 cases). Real Chromium
checks passed for Dashboard, Settings and integration setup; the three Homarr
variants passed compilation/synthetic render checks. Workflow YAML parsed and
shell syntax checks passed. These local results do not replace native Tower
image acceptance or the blocked GitHub Actions jobs.

## Combined exact-image acceptance

Build committed preview code on Tower with the existing pinned-base builder,
then run:

```bash
image=$(bash scripts/sqlite_preview_release_build.sh)
bash scripts/interface_api_release_lab.sh "$image" /mnt/user/sql_test
```

The wrapper requires an immutable local image ID, its packaged preview-only
profile and a revision exactly matching checkout HEAD. It first runs the real
packaged preview startup/binding/manual-worker fixture. Then a second new
container verifies the four HTTP/delivery fixture suites using **packaged app
modules**, not a bind-mounted replacement application. Fixture scripts come from
that same committed revision. The second phase deliberately uses synthetic JSON
inputs/a disposable coordinator; its fixture-only gate stub does not validate or
weaken production binding. Actual binding is validated in the first phase.

All runtime containers have read-only root filesystems, no network beyond private
loopback, no published ports, no production mounts and no Docker socket. Only
new lab files/containers are controlled; logs are retained. No host service,
export, boot, kernel or production notification configuration is changed.
The local build may need access to the pinned base/dependency registries.

CI runs the same combined exact-image wrapper after the full regression suite,
as well as Dashboard/Settings/integration setup browser checks. CI publication
remains a separate explicit input after full acceptance. Billing/spending-limit
failure prevents verification/publication in GitHub; local success is not a claim
that CI or registry publication passed.

## Deployment remains separate

New application revisions require a matching reviewed preview binding. Preserve
current clocks, state, private settings/token files and rollback artifacts. Use
backup-first replacement preparation and review the exact Unraid template before
any service handoff. Do not change only Repository or use an unreviewed floating
tag. Ensure one saved DockerMan template with the primary internal container Name.
Media must remain read-only and permanent deletion disabled. Notification delivery
must remain opt-in; fixture success does not enable real destinations.

Local Apple Silicon builds are arm64 evidence and cannot substitute for Tower's
native image acceptance. The Tower build uses its own native architecture.
