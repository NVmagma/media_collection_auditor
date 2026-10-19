# Feature roadmap

This is the living backlog for Media Collection Auditor. Update it when a feature
is proposed, approved, implemented, deferred, or ruled out. Keep this document
on the active development branch and review it alongside development milestones.

**Last reviewed:** 2026-10-18  
**Active development branch:** `feature/sqlite`  
**Production tracking authority:** JSON  
**Permanent filesystem deletion:** Disabled; requires explicit approval.

## Status key

- **Done** — implemented; retain regression tests and safety guarantees
- **In progress** — actively being developed or validated
- **Planned** — agreed direction; not implemented
- **Proposed** — useful idea, awaiting design or prioritization
- **Approval required** — cannot be enabled or deployed without user approval

## SQLite production-readiness tracker

**Estimated progress: 60%** (milestone-based planning estimate, not a safety
certification). Update this estimate after meaningful verified milestones.
Do not treat it as authorization to deploy or change production storage.

`████████████░░░░░░░░ 60%`

| Milestone | Status |
| --- | --- |
| Experimental SQLite state, snapshots, revision checks | Done |
| Read-only recovery diagnostics, identity, mount and fingerprint observations | Done for current experimental scope |
| Durable pre-move evidence intent checkpoint | Implemented experimentally; CI verification pending |
| Independently trusted recovery and safe reconciliation state machine | In progress / blocked pending design |
| Migration, backup, rollback and production parity | Planned |
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
| Independent verification of interrupted moves and Arr sync | In progress | Read-only filesystem and live-service diagnostic reports can now be combined with revision checks and redaction; read-only shared-ID and fetched-envelope identity checks now reject stale, future-dated and mismatched observations; authenticated read-only Jellyfin/Arr identity fetch orchestration now paired with filesystem status and revision checks; conservative remote path-string comparison now supports movie file-parent and series directory observations, gated on consistent fresh service identities; read-only filesystem object observations now reject symlinks, unstable directory identities, and ambiguous source/destination presence, but cannot prove original object identity; additional regression coverage now checks nested symlink parents, missing destinations, changed device identities and unavailable observations; additional tests now reject symlinked source ancestors, destination files and source appearance during inspection; read-only declared mount-root comparisons now support distinct container path prefixes and optional offline live-identity reporting, but cannot verify mount configurations; read-only metadata fingerprint capture/comparison is now available but not yet recorded before actual moves and cannot prove identity; versioned strict-schema pre-move evidence envelopes are now available for offline experiments, but provenance and durable pre-action ordering remain unverified; experimental intent creation now supports local pre-move evidence capture and durable checkpointing without executing a move, but evidence provenance and cross-container identity remain untrusted; still need verified mount namespace handling, non-atomic scope handling, and independent authorization; never infer success from presence alone |
| Single-snapshot recovery dashboard consistency | Done | Recovery status and readiness checklist derive from one verified SQLite revision; reject unknown statuses |
| Safe reconciliation state machine | Planned | Define permitted transitions and reject ambiguous, stale, or conflicting observations |
| SQLite lifecycle integration | Planned | Optional backend only, with JSON remaining authoritative until explicitly approved |
| JSON-to-SQLite migration and rollback | Planned | Repeatable backup, consistency checks, recovery from failed migration |
| Crash/restart/concurrency and disposable-media testing | Planned | Simulate interrupted moves, failed APIs, container restarts, partial state and races |
| Controlled Unraid SQLite rollout | Approval required | Both CI workflows pass; explicit operator approval and rollback plan |

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

Complete safe SQLite recovery verification, then controlled lifecycle integration,
migration/rollback rehearsals, and Unraid validation. JSON remains authoritative
until the production switch is separately approved.
