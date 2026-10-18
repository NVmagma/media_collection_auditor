# Pre-merge release review — feature/unraid

Status: **review findings, not merge approval**. Keep working on `feature/unraid`.
Do not modify `main`, create `feature/sqlite`, or enable permanent deletion
without explicit user approval.

## Confirmed from source review

| Area | Finding | Recommended disposition |
| --- | --- | --- |
| Auditor state | `collection_auditor.load_state()` validates the JSON structure, timestamps, and pending Arr retry records; unreadable state raises an error rather than resetting history. | Preserve fail-closed behavior; retain regression coverage. |
| State durability | Saves use a uniquely named temporary file, file flush/fsync, atomic replacement, directory fsync on POSIX, and cleanup on failure. | Keep tests for interrupted writes and restart persistence. |
| Dashboard state | `web.load_state()` currently returns `{}` for missing, unreadable, or malformed JSON. This can display a misleading empty collection even when state is unavailable. | Distinguish empty state from read errors in dashboard UI before release. Avoid granting any deletion authorization based on dashboard state. |
| Unraid deployment | `unraid/template/media_archiver.xml` references the old `media_archiver` repository and image; README names `ghcr.io/nvmagma/media_collection_auditor:feature-unraid`. | Confirm intended published image and update template URLs after validation. |
| Compose deployment | `docker-compose.yaml` runs the CLI via `collection_auditor.py` and mounts local `./app`; README describes a dashboard image running `main.py`. | Leave Compose as-is for now; add a separate dashboard Compose example after release if desired. |
| Persistent storage | Default `STATE_FILE` is `/app/logs/auditor_state.json`; Unraid template maps `/app/logs` to appdata. | Verify the actual Unraid host mount and back up existing state before deployment. |
| SQLite migration | Auditor and dashboard use separate JSON loaders. | Plan a shared read-only storage interface on the future SQLite branch, preserving strict auditor validation. |

## Release gate before requesting merge approval

1. Resolve or explicitly accept the dashboard error-display and Unraid image-reference issues.
2. Verify JSON state survives restart, failed writes, and corrupt-file scenarios without resetting clocks.
3. Confirm missing Jellyfin protection signals and ambiguous lifecycle paths cannot authorize deletion; keep permanent filesystem deletion disabled.
4. Check both Python safety checks and Docker Image workflows for the final branch commit.
5. Validate behavior against disposable media and verify appdata persistence on Unraid before any production update.
6. Review the proposed merge with the user and obtain explicit approval before touching `main`.

This document is a source review, not evidence of a production deployment test.
