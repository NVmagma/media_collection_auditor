# Interface/API release record

## Current status — 2026-10-29

Tower is running the explicitly reviewed scheduled-live canary from application
revision `8b2d7198c00a6f8b672a379bf46fc4806165be07`, image digest
`sha256:a929f867ff8d6fcdbca57917d9c7009394a9aa6e21662d5a8025cf129e5cd3d8`.
The service cutover and authenticated readiness passed; the first scheduled
production run is awaiting October 30 review. One global action per daily attempt
remains the limit. Permanent deletion, cross-filesystem moves and season pruning
are disabled. The prior preview container and state are retained.

The newer source adds the shared left sidebar (visually accepted), bounded
per-title scan explanations, journaled live settings application/restoration and
an explicit manual live scan that shares the retained daily claim with the timer.
Focused Linux tests and real browser checks have passed. The expanded packaged
live fixture includes actual manual/timer exclusion, advanced-state settings
application and controller SIGKILL after a manual rename. Full release CI and
publication are tracked separately; none of these source changes updates Tower.

Before installing another image, capture and preserve the **latest live** state,
clocks, Arr queue, daily claims and settings. A new compiled revision requires a
matching reviewed binding. Do not use a stale preview packet, discard claims,
change only Unraid Repository, or automatically start the retained old preview
after live tracking has advanced. First-run verification and any increase beyond
the canary limit remain separate decisions.

## Accepted published candidate — 2026-10-29

- Application revision: `53f7a05603373afd0540a3cc5f6b0a0f2fbd5b08`.
- Immutable reference: `ghcr.io/nvmagma/media_collection_auditor@sha256:006be65b3aa3382038dab6f4eef69328955459dd9363ccf8754b9a78753d728b`.
- Image ID: `sha256:ae5e79e8285ed6cb15f6d98be61666145ed421894142716940c563d8ca4c2f5b`.
- [Acceptance-gated publication](https://github.com/NVmagma/media_collection_auditor/actions/runs/40924534015) passed **3,877 tests and 98 subtests**, nine actual packaged live cases, minimal-capability ownership checks and preview/service recovery acceptance.
- [Python safety and browser checks](https://github.com/NVmagma/media_collection_auditor/actions/runs/40923864505) passed, including flat web import compatibility and real Dashboard/Settings/API browser acceptance.
- The exact accepted image was published without rebuilding. Floating default,
  official and preview references were not changed by this live publication.
- Tower has **not** been updated to this candidate. Wait for the current canary's
  first scheduled result, then prepare a separately reviewed live-to-live update
  preserving the latest state and daily claims. No new template is installed by
  source publication; keep the working pinned live template unchanged.

## Historical preview-only release review — 2026-10-28

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
