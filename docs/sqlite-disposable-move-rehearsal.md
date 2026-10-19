# Disposable-file SQLite recovery rehearsal (proposal; not yet executable)

Status: **design only**. Do not run a filesystem move until the operator
reviews this plan and the dedicated lab mount. This rehearsal is not
production activation or permission to enable reconciliation.

## Existing isolation requirements

Use only the `sqlite-lab` Compose profile and the existing
`scripts.sqlite_lab_preflight` checks. The lab container must have
`network_mode: none`, no privileges, a read-only `/workspace`, and a
single dedicated writable `/lab` bind mount. The pinned Python image,
non-root UID/GID, and host lab directory must be reviewed before any run.
Never bind Jellyfin, Radarr, Sonarr, production appdata, or media libraries.

## Disposable fixture contract

- A new, empty, dedicated `/lab` directory with no symlink ancestors.
- A uniquely named source file with known bytes and an expected SHA-256,
  created inside `/lab` only. Destination must not exist.
- A fresh experimental SQLite snapshot with a durable move intent and
  pre-move evidence before attempting a file operation.
- No cleanup or overwrite on failure; retain fixtures for inspection.
- Read-only inspection must not change either file or SQLite revision.
- All paths must remain inside the reviewed `/lab` mount. Reject symlinks,
  nested mounts, unexpected preexisting fixtures, and unknown file types.

## Crash-window acceptance matrix

| Window | Fixture state | Expected SQLite state | Required behavior |
| --- | --- | --- | --- |
| Before intent | Source only | No pending intent | No move permitted |
| After intent, before move | Source only | `intent_recorded` | Block retry and clearance |
| After disposable move, before applied checkpoint | Destination only | `intent_recorded` | Block retry and clearance |
| After applied checkpoint, before reconciliation | Destination only | `applied_pending_reconciliation` | Block clearance |
| Partial/copy ambiguity | Source and destination | Pending | Block and retain both |
| Missing fixture | Neither | Pending | Block and retain evidence |
| SQLite unavailable or changed | Any | Unverified | Fail closed; do not touch files |

For each row, repeat the read-only inspection after stopping and recreating
the isolated container. Confirm file bytes/hash where applicable, unchanged
SQLite revision, and no external API calls. A destination-only observation
is **not proof** that the expected original file moved.

## Preconditions before executable implementation

1. Review exact host bind mounts, UID/GID, pinned image digest, and preflight.
2. Implement a fixture-only executable with hard-coded, uniquely prefixed
   names and strict `/lab` path guards; never accept arbitrary media paths.
3. Unit-test rejection of symlinks, nested mounts, unexpected files, and
   attempts to overwrite or delete existing data.
4. Run both GitHub Actions workflows successfully.
5. Obtain explicit approval for the isolated disposable-file rehearsal.
   No production media moves or permanent deletion are permitted.

## Rollback and result recording

Do not automatically undo or reconcile an ambiguous operation. Stop the lab,
capture the sanitized status and fixture hashes, and review the state before
manual cleanup of the dedicated disposable directory. JSON remains
authoritative in production; SQLite reconciliation remains disabled.
