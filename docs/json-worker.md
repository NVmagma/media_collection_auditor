# JSON worker operations

The runtime starts `python -B -m app.main` with `AUDITOR_WORKER_MODE=json_serialized`
and `AUDITOR_STATE_BACKEND=json`. Tracking is stored in
`/app/logs/auditor_state.json`; saved web settings use
`/app/logs/auditor_config.json`. Scan history defaults to
`/app/logs/audit_history.jsonl`. Appdata must remain persistent across updates.
See [installation](installation.md) for the current runtime image and mounts.

## Scheduling and action limits

Daily scans use `DAILY_RUN_TIME` and `DAILY_RUN_TIMEZONE`, falling back to `TZ`.
The default daily time is 02:00. Set an explicit time zone to avoid surprises.
Manual live scans require confirmation, share a one-hour cooldown with scheduled
live scans, and cannot overlap. Applying settings does not start a scan.
`RUN_INTERVAL_HOURS` is a legacy setting and does not control this worker's daily
schedule.

Each live scan allows five actions per library and ten overall, with a lower total
configurable through `MAX_ACTIONS_PER_RUN`. Whole-title deletion permits at most
one title per library per scan. Season retention moves one season per show per
scan; season deletion permits at most one season per scan. All share the remaining
action budget. Large collections are scanned beyond the dashboard's display
limits, subject to bounded inventory and request limits.

A Dry Run reads state, files, and services and returns proposals. It performs no
media writes and does not persist discovery clocks. A live scan records eligible
discovery/content-clock changes before executing verified actions.

## Whole-title lifecycle

Waiting titles can move to Holding or Keep. Holding titles can move to Removal
or Keep. `keep`, `keep-forever`, `not-at-all`, and configured favorites influence
those decisions. Every action repeats current protection and Arr identity checks.
Missing or conflicting service information blocks the affected action. Missing
Arr records are skipped and can be reviewed through [existing-folder imports](arr-existing-import.md).

[Removal deletion](removal-deletion.md), [season retention/deletion](tv-season-retention.md),
and [metadata quarantine](orphan-metadata-quarantine.md) have separate policies and
opt-ins. Cross-filesystem copy fallback and the old direct season-pruning switch
remain unsupported. Whole-show actions pause while that show has staged seasons.

## State and interruptions

One nonblocking writer lock covers a live scan. Atomic JSON checkpoints preserve
unknown fields and unrelated lifecycle clocks. Missing/corrupt tracking or saved
settings pause scanning. A durable operation journal is saved before media or
remote mutations; uncertain operations remain pending and are never replayed
automatically. See [Operation recovery](arr-intent-recovery.md).

Saved settings are configured through the WebUI; old template variables remain a migration fallback. Settings apply
atomically for the next scan. Deletion consent is stored separately from the
boolean setting, so an environment flag alone cannot authorize deletion.

## Progress and results

The dashboard polls run status every five seconds. It shows the active phase,
Movies/TV during service collection, processed title checks, total inventory when
known, and elapsed time. A slow request can leave the checked count unchanged.
Progress is process-local and does not claim completion or current inventory
freshness. A restart clears live progress while preserving saved history.

History and Activity Logs distinguish proposals, skipped actions, verified
completions, and uncertain results. Activity summaries include completed season
moves/deletions when recorded. Per-title season actions are not yet represented
as full detail rows in the whole-title results browser.

**Activity Logs → Browse scan results** searches and filters retained attempts
with 25-row pages. New attempts retain whole-title decisions in bounded 100-row
chunks. Older attempts may have only the first 100 display rows and show a partial
history notice. The browser covers the most recent 100 retained attempts. Missing
counts remain unknown, and a historical result does not certify current disk state.

## Maintenance

Create a [private backup](browser-backups.md) before maintenance. It preserves
tracking and saved settings, including pending intents and unknown fields; media,
scan-history files, and any legacy template-only settings need their own backup strategy.

For image updates, retain current appdata/media mounts and review saved schedule,
mode, and deletion consent. Never initialize an existing appdata directory or run
two writers against it. [Installation and updates](installation.md) covers the
`:stable` tag and the native-filesystem requirements.
