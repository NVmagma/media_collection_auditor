<!-- Current candidate update: 2026-10-30 -->

Hourly manual live scans are implemented for the next immutable image: one active
scan, at least sixty minutes between scheduled/manual attempt starts, durable
claims across restart/update, one title action per scan, deletion disabled.
The currently deployed image remains on its daily-budget behavior until the
new image and state-preserving handoff are accepted and deployed.

# Feature roadmap

**Last reviewed:** 2026-10-29
**Official/default branch:** `feature/unraid`
**Active development branch:** `feature/interface-api`
**Tracking authority:** SQLite
**Tower deployment:** Scheduled live canary, one global title action per daily run.
**Permanent deletion / cross-filesystem moves / season pruning:** Disabled.

## Current next work

- Explicit existing-media Arr import is implemented for Sonarr 4 / Radarr 6:
  administrator provider/profile review, existing folder with its stage preserved,
  unmonitored with searches disabled, guarded intent and GET-only recovery.
  See [the import contract](arr-existing-import.md). It is not installed on Tower
  until the next reviewed state-preserving live update. Per-title Arr eligibility
  handling and fuller/paginated decision retention remain separate follow-up work.

- Live canary cutover and authenticated readiness completed on Tower on October
  29. Its first scheduled run is awaiting October 30 observation. Keep the
  one-action cap until that result is reviewed; deployment is not evidence of a
  successful production media move.
- Shared left navigation is implemented, browser/CI tested and visually accepted.
  Those newer UI sources are not yet deployed to Tower.
- Per-title scan explanations are implemented with bounded process-local records:
  fixed policy reasons, separate proposed/completed/uncertain outcomes and
  retained verified move observations when later Arr delivery fails. Counts-only
  integration APIs continue omitting title details. Exact-image acceptance passed.
- Reviewed live settings application/recovery and an explicit manual live run
  passed exact-image acceptance and publication. Settings preserve advanced
  tracking and daily claims; manual runs share the timer’s durable local-date
  claim and one-action cap. These newer controls are not yet installed on Tower.
- Release notes and immutable publication are recorded in the
  [current release record](interface-api-release-review.md). Next deployment must
  use a reviewed live-to-live update preserving latest tracking and daily claims;
  leave the working pinned Unraid template unchanged while awaiting first-run review.

## Completed SQLite preview milestone

All ten preview-scope gates are closed, including retained-clock restoration,
real Tower cutover/recovery evidence, dashboard/Jellyfin navigation, Homarr movie
and TV views, manual read-only scans and the final saved Unraid template.
Application e537ba5 passed 3,361 tests and 82 subtests plus actual-image/manual
request acceptance. Follow the [branch workflow](branch-workflow.md) and
[final acceptance record](sqlite-gate10-release.md). Old progress percentages and
JSON-authority milestones below are historical and no longer describe this release.

## Next interface/API development priorities

| Priority | Work | Acceptance |
| --- | --- | --- |
| P0 | Installation/update workflow | Preserve state/clocks/settings; validate bindings; detect duplicate internal Unraid template names; preview actual recreate configuration before updates; retain recovery evidence |
| P0 | Clear preview-mode UI | Distinguish filesystem inventory from tracking counts; show unknown dates honestly; make frozen settings/rebinding clear; expose running/queued/manual/daily status without enabling moves |
| P1 | Dashboard layout/navigation | Consistent title-link and visited-link colors, table/poster control visibility, spacing, mobile/accessibility, loading/error/empty states |
| P1 | Richer Homarr/Homepage widgets | Compact poster/backdrop cards and badges; separate movie/TV Leaving soon and oldest Waiting views; correct query configuration; safe image caching and Jellyfin navigation |
| P1 | API contract and diagnostics | Version/readiness, clear auth-versus-route errors, snapshot provenance/freshness semantics, consistent filtering and pagination, token rotation and useful redacted diagnostics |
| P1 | TV tracking visibility | Explain no Holding records versus unavailable data; preserve whole-show protections and clocks; define explicit initialization when retained TV records are missing |
| P2 | Scan/history usability | Clear preview proposals and discovery differences; actual scan counts/results; distinguish process-local history from durable tracking; do not fabricate completion or freshness |
| P2 | Security/release maintenance | Retarget dependency updates to official branch; keep CVE checks and exact-source/image acceptance; review findings without weakening tests |

Live action activation, portable copy/promotion/source cleanup, season pruning,
permanent deletion and host-wide NFS/boot fencing remain separate future scopes.
Interface/API work does not authorize them. Do not auto-update Tower on merges.

## Historical planning notes (superseded by the milestone above)

## Status key

- **Done** — implemented; retain regression tests and safety guarantees
- **In progress** — actively being developed or validated
- **Planned** — agreed direction; not implemented
- **Proposed** — useful idea, awaiting design or prioritization
- **Approval required** — cannot be enabled or deployed without user approval

## SQLite production-readiness tracker

**Estimated progress: 78%** (milestone-based planning estimate, not a safety
certification). Update this estimate after meaningful verified milestones.
Do not treat it as authorization to deploy or change production storage.

`████████████████░░░░ 78%`

| Milestone | Status |
| --- | --- |
| Experimental SQLite state, snapshots, revision checks | Done |
| Read-only recovery diagnostics, identity, mount and fingerprint observations | Done for current experimental scope |
| Durable pre-move evidence intent checkpoint | Done for experimental scope; persisted read-only inspection added, CI pending |
| Independently trusted recovery and safe reconciliation state machine | In progress / blocked pending design |
| Migration, backup, rollback and production parity | In progress; interrupted conversion and incomplete-snapshot rehearsals added, CI pending |
| Crash/restart, disposable-media and Unraid validation | Planned |
| Controlled production cutover | Approval required |

## P0 — SQLite storage and recovery readiness

| Feature | Status | Acceptance / next step |
| --- | --- | --- |
| Experimental SQLite state storage, migration snapshot, revisioned audit session | Done | Maintain tests for atomicity, revision conflicts, and state integrity |
| Recovery intent checkpoints and fail-closed operation coordinator | Done | Keep unresolved operations blocked until independent verification |
| Offline recovery CLI, admin-only API, read-only recovery page | Done | Preserve redaction, authorization, and no-write guarantees |
| Opt-in dashboard integration and navigation | Done | Default off; only admin users can inspect |
| Human-readable recovery blocker guidance | In progress | Explain known failure modes without granting clearance |
| Independent verification of interrupted moves and Arr sync | In progress | Read-only filesystem and live-service diagnostic reports can now be combined with revision checks and redaction; read-only shared-ID and fetched-envelope identity checks now reject stale, future-dated and mismatched observations; authenticated read-only Jellyfin/Arr identity fetch orchestration now paired with filesystem status and revision checks; conservative remote path-string comparison now supports movie file-parent and series directory observations, gated on consistent fresh service identities; read-only filesystem object observations now reject symlinks, unstable directory identities, and ambiguous source/destination presence, but cannot prove original object identity; additional regression coverage now checks nested symlink parents, missing destinations, changed device identities and unavailable observations; additional tests now reject symlinked source ancestors, destination files and source appearance during inspection; read-only declared mount-root comparisons now support distinct container path prefixes and optional offline live-identity reporting, but cannot verify mount configurations; read-only metadata fingerprint capture/comparison is now available but not yet recorded before actual moves and cannot prove identity; versioned strict-schema pre-move evidence envelopes are now available for offline experiments, but provenance and durable pre-action ordering remain unverified; experimental intent creation now supports local pre-move evidence capture and durable checkpointing without executing a move; persisted fingerprints can now be inspected after restart against source and destination with revision-race detection and included in a sanitized offline combined report that checks operation and revision stability, but cannot authorize recovery, but evidence provenance and cross-container identity remain untrusted; still need verified mount namespace handling, non-atomic scope handling, and independent authorization; never infer success from presence alone |
| Single-snapshot recovery dashboard consistency | Done | Recovery status and readiness checklist derive from one verified SQLite revision; reject unknown statuses |
| Safe reconciliation state machine | In progress | Offline consolidated evidence now includes filesystem status and a fail-closed decision matrix with revision guards; decision matrix classifies duplicate/missing locations, service identity, mount mapping and cross-device uncertainty; no clearance transitions are enabled |
| SQLite lifecycle integration | Planned | Optional backend only, with JSON remaining authoritative until explicitly approved |
| JSON-to-SQLite migration and rollback | In progress | Offline interrupted-conversion and incomplete-snapshot regression rehearsals added; preserve authoritative JSON, require disposable Unraid validation before cutover |
| Crash/restart/concurrency and disposable-media testing | In progress | Disposable SQLite restart, stale revision and uncertain checkpoint rehearsals added (CI pending); disposable-media restart diagnostics added (CI pending); still need actual Unraid container restarts and external API failure tests |
| Controlled Unraid SQLite rollout | Approval required | Isolated lab-only rehearsal checklist: [Unraid SQLite lab validation](unraid-sqlite-lab-validation.md); dedicated offline Compose lab configuration added (CI pending); real container restart evidence still required; explicit operator approval and rollback plan |

## P1 — Security maintenance and CVE monitoring

| Feature | Status | Acceptance / next step |
| --- | --- | --- |
| Dependabot vulnerability alerts and security update PRs | In progress | Weekly pip, Docker, and GitHub Actions update PRs configured for feature/sqlite; confirm private-repository alerts and PR creation in GitHub settings |
| Automated Docker image CVE scanning | In progress | Trivy local-image scan added on PRs and weekly schedule; validate workflow and triage any findings |
| CodeQL static security analysis | Planned | Confirm private-repository eligibility and run on pull requests and a weekly schedule; investigate actionable findings |
| Weekly security review and urgent CVE triage | In progress | Weekly scheduled pip-audit and Trivy workflow added; establish recurring human review and escalate urgent findings immediately |
| Dependency and Docker base-image update policy | Planned | Use reproducible versions/digests where practical; review updates regularly, run regression tests, and verify both workflows before recommending deployment |
| Security policy and vulnerability reporting | In progress | SECURITY.md added; confirm private vulnerability reporting is enabled and contact route works |
| Safe security release procedure for Unraid | Planned | Document tested fixes, rollback steps and operator approval; never automatically update production or relax deletion safeguards |

## P1 — Dashboard and operations

| Feature | Status | Acceptance / next step |
| --- | --- | --- |
| Accurate Waiting, Holding, Keep, Removal counts and lifecycle ages | In progress | Match filesystem and tracking records; warn on unavailable inputs |
| Clearer state tracking and useful audit/recovery logs | Planned | Surface actionable causes without leaking tokens or paths |
| Removed History and Re-download dashboard controls | Proposed | Design safe history and intentional re-download workflows; avoid accidental Arr re-download |
| Improved audit run visibility and failure diagnostics | Proposed | Explain what changed, what was skipped, and why |
| HTTPS dashboard access | Planned | Document reverse-proxy deployment (Caddy/Nginx Proxy Manager/Traefik), secure cookies and trusted proxy settings |
| HTTPS connections to Jellyfin/Radarr/Sonarr | Planned | Verify certificates, support custom CA as needed; never silently disable TLS validation |

## P1 — Media lifecycle and protection

| Feature | Status | Acceptance / next step |
| --- | --- | --- |
| `keep`, `keep-forever`, `keep-all-seasons`, `not-at-all` Jellyfin tags | Done | Preserve title-wide and season-wide protection semantics |
| Jellyfin favorites via `FAVORITES_TRIGGER_KEEP` | Done | Maintain compatibility and fail closed if protection data is unavailable |
| Reliable Jellyfin refresh after successful moves | Done | Preserve best-effort refresh and useful failure logs |
| Radarr/Sonarr synchronization and protection against unintended downloads | In progress | Validate identity, service failures, and reconciliation |
| Permanent filesystem deletion | Approval required | Must remain disabled until explicitly authorized; test only on disposable media first |

## P2 — Future ideas

| Feature | Status | Acceptance / next step |
| --- | --- | --- |
| Operator-friendly SQLite readiness checklist | In progress | Read-only recovery checklist added; extend with independently verified evidence and migration tests before optional rollout |
| Backup and restore validation tooling | Proposed | Provide non-destructive state consistency and restore rehearsal |

## How to maintain this roadmap

1. When a new idea comes up, add it here as **Proposed** with a short acceptance criterion; don't treat a suggestion as approval to enable it.
2. When work is selected, mark **In progress** and reference its branch or milestone in the commit or PR.
3. Mark **Done** only after relevant tests and GitHub Actions pass; deployment is a separate decision.
4. Preserve explicit approval gates for deletion, production backend switches, and container updates.
5. Review priorities after each cohesive milestone. Prefer P0 safety and state integrity before convenience features; treat urgent security vulnerabilities as an exception requiring prompt triage.

## Current focus

See [SQLite recovery acceptance review](sqlite-recovery-acceptance-review.md)\nfor the prioritized gaps, verified evidence, and explicit production gates.\n\n
Complete safe SQLite recovery verification, then controlled lifecycle integration,
migration/rollback rehearsals, and Unraid validation. JSON remains authoritative
until the production switch is separately approved.

## Interface/API branch progress

- First update-reliability increment: read-only saved-template/container comparison,
  including duplicate internal names and lost control mounts. This is a diagnostic,
  not a completed safe updater or binding migration. See [usage](unraid-update-review.md).
- Square transparent app icon prepared; future explicit images serve it without
  credentials. Existing private GitHub asset URLs cannot serve as anonymous icons.

- Proposed cached-image review now checks the packaged preview contract and full
  existing binding; a changed source revision requires fresh preparation. Local
  eight-case lab and nine-case fresh-instance acceptance passed. Backup-first
  update planning and production recreation remain outstanding.

- Backup-first update capture/inspection implemented for disposable acceptance:
  full logical tracking/settings snapshots, private files, durable incomplete
  markers, exact-content verification and no automatic replay. Replacement
  binding preparation and the container swap/recovery are not yet implemented.

- Replacement binding preparation now preserves the verified logical snapshot
  and settings in new private roots; original binding/files are retained.
  Disposable acceptance is required before the service swap/recovery milestone.

- Fixture-only container swap/recovery now has durable intent records, explicit
  recovery, lost-acknowledgement refusal and an actual controller SIGKILL rehearsal.
  Local 25-case fault lab and actual-image HTTP/recovery tests passed; Tower
  acceptance is next. Production update orchestration remains a separate step.

- October 27: compact Homarr movie rows passed user fixture and production
  preview acceptance. Separate TV/movie templates and synthetic loading/error/
  empty checks are available. No auditor image update is required for templates.
- Dashboard navigation polish: consistent visited/unvisited Jellyfin title
  colors, visible keyboard focus, and narrow-screen wrapping prepared. Browser
  acceptance and deployment remain pending; no lifecycle or tracking changes.

- Hybrid dashboard foundation: Overview/Library/Scans/Activity/History workspace
  navigation, contextual movie/TV and table/poster controls, scoped dashboard
  spacing and clearer tracking-versus-folder totals. Existing action handlers and
  administrator restrictions are retained. Sixty focused Python checks passed
  on Linux; Chromium exercised page/library/stage/view switching and storage
  preference behavior at 1280/736/390/320px with synthetic intercepted responses.
  Production remains unchanged; candidate image and Tower acceptance pending.

- Hybrid Library increment: local title search, alphabetical sorting and a
  keyboard-accessible read-only details panel reuse the rendered inventory and
  existing explanations. Filtered result counts stay separate from stage totals.
  Linux dashboard/API regression checks and Chromium interaction checks passed;
  a synthetic expiring Tower visual preview is ready. See
  [redesign scope and preview](dashboard-redesign.md). No production update yet.

- Operations Overview increment: explicit coverage/scheduler attention findings,
  compact scheduler and proposal observations, and bounded Leaving soon/Oldest
  waiting lists from the same enriched folder snapshot. Title selection opens
  the correct Library stage/inspector. Missing clocks, partial directories and
  unavailable tracking remain distinct. Positive user feedback recorded for the
  preceding shell/Library preview. Overview passed 148 focused Linux checks plus
  real Chromium/private HTTP checks; Tower visual acceptance remains pending.

- User-requested Overview simplification: detailed coverage and collection
  findings moved to a separate authenticated `/review` page. Overview retains
  short attention summaries, three-title lists and direct review links. The
  representative desktop Overview fits without scrolling at 1280×1000 and
  1440×1000 with administrator controls; mobile remains readable and naturally
  scrolls. Linux regressions (150) and real browser page/focus/layout checks pass.
  Production is unchanged; the revised disposable preview awaits user review.

- Scans/History modernization: current scheduler observations and the latest
  recorded outcome are separated from saved-date timer estimates. SQLite attempt
  history now has scalar-only outcome details, configured-zone times, durations,
  result filters and five-entry pages. Preview proposals and completed moves/Arr
  updates remain separate; unknown counts and unrecorded per-title skip/block
  reasons stay explicit. No coordinator persistence or execution changes.
  Legacy JSON history stays compatible. User acceptance recorded for the prior
  separate Review/compact Overview increment. New Scans/History passed 191 Linux
  checks (including both runtime layouts) and real Chromium interaction checks;
  disposable Tower visual review is pending.

- Settings presentation increment: three-stage active/request/application status,
  local-only unsaved field indicators, private requested field-name summaries,
  and clearer interrupted/recovery presentation. Apply/restore/backend safeguards
  are unchanged. Positive user feedback recorded for Scans/History. Settings
  passed 117 Linux tests and 8 subtests plus real browser/private HTTP checks;
  the synthetic Tower Settings preview is ready for visual review.

- Preview Settings simplification: one Apply Requested Settings action stages and
  applies the exact validated request. Removed the separate preview save button
  and typed acknowledgement. Recovery and legacy live-mode confirmations remain.
  Verified with 128 Linux tests, 8 subtests and Chromium form/layout checks.
  Production remains unchanged; GitHub Actions billing remains an external blocker.

- API setup increment: authenticated `/api/v1/readiness` and administrator-only
  `/integrations` with credential-free copy controls, movie/TV query instructions,
  explicit auth/route/unavailable diagnostics and token-replacement guidance.
  Preview binding failures remain diagnosable without unbound tracking reads.
  See [contract and future API proposals](integration-api-setup.md).
  Token replacement remains an explicit container operation; no secrets are
  displayed or rotated by the setup page. Production remains unchanged.
  Verified with 216 Linux integration/security/runtime checks, two additional
  fixture/token tests and Chromium copy/responsive checks; existing Dashboard and
  Settings browser checks also pass. Tower visual acceptance remains pending.

- Coverage API: opt-in authenticated `/api/v1/coverage`, optional movie/TV filter,
  aggregate-only Review parity, bounded local folder reads and explicit incomplete
  totals. Selected SQLite identity/revision checks span inventory collection;
  changed JSON/settings also invalidate the report. No clocks/state/media writes.
  Verified with 239 Linux regression tests, five real loopback HTTP cases and
  Chromium setup-page checks. Disposable Tower HTTP acceptance is next; production
  remains unchanged and no image publication is claimed while CI billing is blocked.
- User visual acceptance recorded for the API setup page on Tower port 18091.

- Tower coverage acceptance recorded for revision 8225f86: all five private HTTP
  cases passed on `/mnt/user/sql_test`; production services and media unchanged.
- Scan observation APIs: `/api/v1/scan-history` adds bounded page/outcome filtering;
  `/api/v1/proposals` reports latest recorded preview counts, never fabricated
  per-title plans. One coordinator lock captures current status and retained history.
  Restart-local scope, unknown counts and separate-service unavailability remain
  explicit. No history persistence, worker execution or media authority added.
  Verified with 278 Linux regressions, five actual loopback HTTP tests and browser
  checks for setup guidance. Disposable Tower scan API acceptance is next.

- Tower scan API acceptance recorded for revision 8429c3e: five real loopback HTTP
  cases passed; no production worker/state/services connected.
- Backup status API: authenticated `/api/v1/backup-status` verifies one explicitly
  pinned private logical packet using the shared update/recovery inspector. It
  never discovers or creates backups, compares current tracking or grants restore
  authority. New receipts record capture time; legacy age remains unknown.
  Verified with 317 Linux integration/backup/update/recovery/security regressions,
  five actual loopback HTTP cases and setup browser checks. Disposable Tower
  backup-status acceptance is next; production remains unchanged.

- Tower backup-status acceptance recorded for revision 32ce7bb: all five packet
  verification HTTP cases passed; no production services or restore actions used.
- Operational failure alerts: new default-off setting, existing Discord/ntfy/custom
  destinations, fixed redacted messages, per-incident process suppression and no
  automatic delivery retries. Scheduler and Settings hooks preserve transaction
  outcomes, replay claims and tracking. Preview requires Notify During Dry Runs.
  Existing JSON digests remain unchanged. See [delivery contract](operational-notifications.md).
  Verified with 361 Linux regression checks across focused runs (including the
  two corrected Settings-hook tests), eight subtests, five actual loopback delivery
  cases and Settings browser checks. Tower delivery acceptance is next; no real
  notification targets or production services were contacted.

- Tower operational notification acceptance recorded for a6fc8c0: all five private
  delivery cases passed, with no external or production notification delivery.
- Combined interface/API release review: 3,656 full Linux regressions and 98
  subtests passed, plus 20 private HTTP/delivery cases and Dashboard/Settings/API
  setup browser checks. Homarr synthetic render checks passed. CI now includes the
  combined exact-image harness and integration setup browser acceptance. A build
  retry remained blocked before execution by GitHub billing. No merge, registry
  publication or production deployment was performed. Native exact-image Tower
  acceptance remains next; see [release review](interface-api-release-review.md).

- Native Tower combined-image acceptance recorded for ce58bd5, image
  `sha256:ef3c95d577fd94fbf95d8436588c5d8883811c389c1dd2578a22175273025e75`:
  16 actual preview/binding cases and all 20 packaged HTTP/delivery cases passed.
  No registry publication or production handoff occurred.
- Different-image offline preparation controller: creates only new private
  binding/log roots from one pinned backup; no service payload, registry reference
  or deployment authority. Fixed backup-tool compatibility with older packaged
  recovery modules; tested against e537ba5 modules using synthetic data. Seventy
  focused Linux preparation/backup/recovery checks passed. Fresh Tower backup
  capture is next; current state and service configuration remain unchanged.

- Candidate preparation preflight correction: ignore Docker formatting-only blank
  lines before exact bind-layout comparison; retain rejection of extra binds.
  Added named redacted failure diagnostics and a shell-level reproduction test.
  No production or private preparation files are changed by this correction.

### Scheduled catalog request budget

Inventory titles share detached Jellyfin GET pages within one scan pass. The
pass has a 64 MiB response budget and retains the existing transport request and
run deadline limits. Every inventory rebuild clears these pages, including the
rebuild after discovery clock checkpointing. User coverage, pagination, item
identity and protection field validation still run for each title. A transport
failure invalidates the pass catalog without automatic retry. Pre-move protection
reads always use the original uncached transport; scan-time signals never
authorize a move. This reduces redundant catalog requests without increasing
the one-action cap or enabling deletion.

### Future-dated TV content

A TV Waiting title with a descendant modification time later than the scan
observation is skipped with `future_content_timestamp`. Its lifecycle clock is
neither initialized nor reset, and no move is authorized for it. Other titles
may continue after the complete inventory barrier. Unreadable content, symlinks,
changed entries, and content scan limits still abort the attempt. Tests include
a real disposable movie rename alongside a retained future-dated TV episode.

### Arr remote directory path compatibility

Radarr/Sonarr catalog and per-title responses may use one trailing slash on
an otherwise canonical absolute POSIX directory path. The Arr boundary removes
that optional slash for identity comparisons. Configuration and filesystem paths
remain strict; duplicate separators, dot/traversal segments, roots, relative paths
and backslashes are not repaired. Normalized duplicate folder matches still
block. Both independent update readbacks must match the expected title ID,
monitoring state and complete destination path.

### Jellyfin refresh after scheduled live moves

The SQLite live worker honors `JELLYFIN_REFRESH_AFTER_AUDIT` (default false).
After a fully completed batch and its Arr updates, it sends at most one
`POST /Library/Refresh` with modern and legacy authentication headers. Preview,
no-move, stopped and uncertain outcomes do not request refresh. Requests use the
remaining run budget, a maximum ten-second timeout, no proxy inheritance, no
redirects and no retries. A failure is logged with fixed redacted text and never
changes completed tracking or replays media actions. An accepted response only
means a library scan was requested, not that Jellyfin has finished indexing.
The Holding/Keep/Removal paths must already be included in Jellyfin libraries
if moved titles should remain available for playback.

### Grouped Jellyfin presentation lookups

Dashboard link/poster and Homarr catalog requests explicitly disable collection
collapsing, as the scheduled protection collector already does. Otherwise a
collection can hide its individual movies and cause the Auditor's local
`Title not found in Jellyfin` response. Presentation caches expire after five
minutes; a subsequent lookup resolves the current catalog item ID rather than
persisting a pre-move ID. This does not verify indexing completion or alter
Jellyfin library paths.

### Independent Movie and TV live slots

A reviewed live binding may retain the original `MAX_ACTIONS_PER_RUN=1` global
cap, or explicitly select `MAX_ACTIONS_PER_RUN=2` for one Movie and one TV action
per scan. The latter is a two-action ceiling, not two transferable actions: a
second Movie cannot consume TV's slot, even with TV disabled or no eligible show.
The executor independently validates library counts before opening operation
state. Complete collection, discovery checkpoint/rebuild, fresh per-move
protection, no-replace rename and Arr acknowledgment rules remain unchanged. An
uncertain operation still stops the batch and prevents replay.

Existing installations keep their bound limit until an explicit offline live
update uses `unraid_live_update_prepare_host.sh ... --library-slots`. This
preserves advanced tracking and every durable scan claim, changes only
`MAX_ACTIONS_PER_RUN`, and requires the usual review/preflight/deploy transaction.
The maximum stays locked in live settings. Manual and scheduled attempts still
share the 60-minute cooldown and scan lock. Permanent deletion stays disabled.
The dashboard, API and cutover health checks report the two-slot contract.
