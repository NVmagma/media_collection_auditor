# Official release and development branches

- **Official/default branch:** `feature/unraid`.
- **Next development branch:** `feature/interface-api`.
- **Completed branch:** `feature/sqlite`; merged through its recorded pull request
  and retained through the `sqlite-preview-complete-2026-10-26` archive tag.

The accepted official scope is the SQLite scheduled **preview** release. Tracking
is SQLite, media stays read-only, manual Run Preview Now is read-only, and live
moves/deletion remain disabled. Branch promotion does not change Tower, its
immutable image, application binding, private paths, credentials or settings.

Use small commits and PRs from `feature/interface-api` to `feature/unraid`. The
full regression suite plus actual candidate/preview container, migration,
restore, authenticated API, manual preview and host-wrapper checks run against
the exact PR head. A same-repository PR checkout is required for this private
acceptance workflow. A changed head fails exact-source verification instead of
silently testing a different revision. Review advisory security findings as well.

The official Docker Image workflow now reuses the same acceptance pipeline.
Publication is manual, opt-in, after acceptance, under a commit/image-specific
preview tag. Merging never publishes over `latest` or `feature-unraid`, and never
deploys Tower. The older flat Dockerfile remains a legacy recipe, not the
accepted preview publication path; the explicit recipe under `docker/` packages
all modules. Do not edit the tracked Dockerfile/dockerfile case collision from a
case-insensitive checkout simply to make its worktree look clean.

New app code needs a matching reviewed preview binding before deployment. Do not
change only Unraid's Repository, reset tracking, edit binding records, or assume a
floating image tag is a release permit. Preserve current state and rollback
artifacts. DockerMan must have exactly one saved XML with the primary container's
internal Name; duplicate XML names previously caused an old image/mount rollback.

Historical acceptance commands may refer to feature/sqlite. Use the official or
approved development branch for new builds/controllers and a tested exact commit.
Old records remain historical evidence, not current deployment instructions.
See [completion gates](sqlite_completion_gates.md), [deployment record](sqlite-production-cutover-runbook.md),
and the [current roadmap](feature-roadmap.md).
